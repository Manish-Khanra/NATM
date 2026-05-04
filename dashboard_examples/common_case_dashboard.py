from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pandas as pd

try:
    import networkx as nx
    import solara
    from matplotlib.figure import Figure
    from matplotlib.patches import Polygon
    from matplotlib.ticker import FuncFormatter
    from mesa.visualization import SolaraViz, make_plot_component
    from mesa.visualization.utils import update_counter
except ModuleNotFoundError as exc:  # pragma: no cover - optional dashboard dependency
    missing_package = exc.name or "dashboard dependency"
    raise RuntimeError(
        "Dashboard dependencies are missing. Install them with "
        "`python -m pip install -e .[dashboard]` before running this example. "
        f"Missing package: {missing_package}",
    ) from exc

from navaero_transition_model.cli import resolve_case_config
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import NATMScenario

KWH_PER_TWH = 1_000_000_000.0
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "simulation_results"
PROCESSED_AVIATION_ROOT = PROJECT_ROOT / "data" / "processed" / "aviation"
EMISSION_COLUMN_METADATA = {
    "total_emission": {"label": "Total emissions", "unit": "tonnes"},
    "chargeable_emission": {"label": "Chargeable emissions", "unit": "tonnes"},
    "co2_kg": {"label": "CO2", "unit": "tonnes"},
    "total_co2_kg": {"label": "CO2", "unit": "tonnes"},
    "h2o_kg": {"label": "H2O", "unit": "tonnes"},
    "nox_kg": {"label": "NOx", "unit": "tonnes"},
    "total_nox_kg": {"label": "NOx", "unit": "tonnes"},
    "co_kg": {"label": "CO", "unit": "tonnes"},
    "hc_kg": {"label": "HC", "unit": "tonnes"},
    "soot_kg": {"label": "Soot", "unit": "tonnes"},
    "sox_kg": {"label": "SOx", "unit": "tonnes"},
}
EMISSION_KG_TO_TONNES = 1_000.0
EUROPE_BASEMAP_POLYGONS = [
    [
        (-10.0, 36.0),
        (-9.4, 43.8),
        (-5.0, 48.5),
        (-1.5, 50.4),
        (4.5, 53.7),
        (8.8, 54.9),
        (13.8, 54.7),
        (18.8, 56.2),
        (24.5, 59.9),
        (31.5, 60.8),
        (33.0, 55.5),
        (30.0, 50.0),
        (25.0, 45.0),
        (22.0, 40.5),
        (19.0, 39.0),
        (15.2, 40.0),
        (12.0, 43.2),
        (8.2, 43.8),
        (3.2, 43.1),
        (-1.8, 41.0),
        (-6.0, 36.5),
    ],
    [(-8.7, 50.0), (-5.5, 58.4), (-2.0, 58.8), (1.7, 52.0), (-2.5, 50.0)],
    [(-10.8, 51.4), (-9.0, 55.4), (-6.0, 55.1), (-5.2, 52.0), (-8.0, 51.2)],
    [
        (5.5, 58.0),
        (10.0, 63.5),
        (17.8, 68.5),
        (25.5, 69.7),
        (30.0, 66.0),
        (23.0, 60.0),
        (13.0, 55.3),
    ],
    [
        (7.0, 44.8),
        (10.5, 46.0),
        (13.5, 43.0),
        (15.6, 40.1),
        (16.2, 37.4),
        (13.0, 38.8),
        (10.0, 42.0),
    ],
]


def _compact_number_formatter(unit_suffix: str = ""):
    def _format(value: float, _position: int) -> str:
        absolute_value = abs(value)
        if absolute_value >= 1_000_000_000:
            scaled = value / 1_000_000_000
            suffix = "B"
        elif absolute_value >= 1_000_000:
            scaled = value / 1_000_000
            suffix = "M"
        elif absolute_value >= 1_000:
            scaled = value / 1_000
            suffix = "K"
        else:
            scaled = value
            suffix = ""
        return f"{scaled:,.1f}{suffix}{unit_suffix}"

    return FuncFormatter(_format)


def _decimal_formatter(decimals: int = 2, unit_suffix: str = ""):
    def _format(value: float, _position: int) -> str:
        return f"{value:,.{decimals}f}{unit_suffix}"

    return FuncFormatter(_format)


def _show_figure(fig: Figure) -> None:
    buf = BytesIO()
    fig.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        pad_inches=0.22,
        dpi=110,
    )
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode("ascii")
    solara.HTML(
        tag="div",
        unsafe_innerHTML=(
            f'<img src="data:image/png;base64,{data}" style="width:100%;height:auto;display:block">'
        ),
    )


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _filter_application(frame: pd.DataFrame, application_name: str) -> pd.DataFrame:
    if frame.empty or "application_name" not in frame.columns:
        return frame.copy()
    return frame.loc[frame["application_name"].astype(str).eq(application_name)].copy()


def _latest_year(frame: pd.DataFrame) -> int | None:
    if frame.empty or "year" not in frame.columns:
        return None
    years = pd.to_numeric(frame["year"], errors="coerce").dropna()
    return int(years.max()) if not years.empty else None


def _emission_columns(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    return [
        column
        for column in EMISSION_COLUMN_METADATA
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").notna().any()
    ]


def _emission_label(column: str) -> str:
    return EMISSION_COLUMN_METADATA.get(column, {"label": column})["label"]


def _emission_totals_table(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        value_kg = pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum()
        rows.append(
            {
                "pollutant": _emission_label(column),
                "source_column": column,
                "emissions_tonnes": value_kg / EMISSION_KG_TO_TONNES,
            }
        )
    return pd.DataFrame(rows).sort_values("emissions_tonnes", ascending=False)


def _show_dataframe(frame: pd.DataFrame, max_rows: int = 12) -> None:
    if frame.empty:
        solara.Markdown("_No rows available._")
        return
    display_frame = frame.head(max_rows).copy()
    for column in display_frame.columns:
        if pd.api.types.is_numeric_dtype(display_frame[column]):
            display_frame[column] = display_frame[column].round(4)
    table_html = display_frame.to_html(index=False, escape=True, classes="natm-table")
    solara.HTML(
        tag="div",
        unsafe_innerHTML=(
            "<style>"
            ".natm-table{border-collapse:collapse;width:100%;font-size:0.88rem;}"
            ".natm-table th,.natm-table td{border:1px solid #ddd;padding:6px 8px;}"
            ".natm-table th{background:#f5f5f5;text-align:left;}"
            "</style>"
            f"{table_html}"
        ),
    )


def _normalize_airport_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["airport_code", "airport_name", "country", "latitude", "longitude"],
        )
    normalized = frame.copy()
    rename_map = {
        "iata": "airport_code",
        "airport": "airport_code",
        "airport_iata": "airport_code",
        "latitude_deg": "latitude",
        "longitude_deg": "longitude",
        "lat": "latitude",
        "lon": "longitude",
        "name": "airport_name",
    }
    normalized = normalized.rename(columns=rename_map)
    if "airport_code" not in normalized.columns and "icao" in normalized.columns:
        normalized["airport_code"] = normalized["icao"]
    for column in ("airport_code", "airport_name", "country"):
        if column not in normalized.columns:
            normalized[column] = ""
    if "latitude" not in normalized.columns or "longitude" not in normalized.columns:
        return pd.DataFrame(
            columns=["airport_code", "airport_name", "country", "latitude", "longitude"],
        )
    normalized["airport_code"] = normalized["airport_code"].astype(str).str.upper().str.strip()
    normalized["latitude"] = pd.to_numeric(normalized["latitude"], errors="coerce")
    normalized["longitude"] = pd.to_numeric(normalized["longitude"], errors="coerce")
    return normalized.dropna(subset=["airport_code", "latitude", "longitude"])[
        ["airport_code", "airport_name", "country", "latitude", "longitude"]
    ].drop_duplicates(subset=["airport_code"], keep="first")


def _normalize_airport_fuel_demand(
    frame: pd.DataFrame, airport_metadata: pd.DataFrame
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    normalized = frame.rename(
        columns={
            "airport": "airport_code",
            "airport_iata": "airport_code",
            "lat": "latitude",
            "lon": "longitude",
        },
    ).copy()
    if "airport_code" not in normalized.columns:
        return pd.DataFrame()
    normalized["airport_code"] = normalized["airport_code"].astype(str).str.upper().str.strip()
    for column in (
        "latitude",
        "longitude",
        "fuel_demand",
        "fuel_uplift_mwh",
        "fuel_uplift_kg",
        "energy_demand",
        "co2",
        "trips",
        "year",
    ):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if not airport_metadata.empty:
        metadata_columns = [
            column
            for column in ("airport_name", "country", "latitude", "longitude")
            if column not in normalized.columns
        ]
        if metadata_columns:
            normalized = normalized.merge(
                airport_metadata[["airport_code", *metadata_columns]],
                on="airport_code",
                how="left",
            )
    if not {"latitude", "longitude"}.issubset(normalized.columns):
        return pd.DataFrame()
    return normalized.dropna(subset=["airport_code", "latitude", "longitude"])


def _normalize_route_energy_flow(
    frame: pd.DataFrame, airport_metadata: pd.DataFrame
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    normalized = frame.rename(
        columns={
            "origin_airport": "origin",
            "destination_airport": "destination",
            "origin_lat": "origin_latitude",
            "origin_lon": "origin_longitude",
            "destination_lat": "destination_latitude",
            "destination_lon": "destination_longitude",
        },
    ).copy()
    if not {"origin", "destination"}.issubset(normalized.columns):
        return pd.DataFrame()
    normalized["origin"] = normalized["origin"].astype(str).str.upper().str.strip()
    normalized["destination"] = normalized["destination"].astype(str).str.upper().str.strip()
    for column in (
        "origin_latitude",
        "origin_longitude",
        "destination_latitude",
        "destination_longitude",
        "fuel_demand",
        "fuel_uplift_mwh",
        "fuel_uplift_kg",
        "energy_demand",
        "co2",
        "trips",
        "year",
    ):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    coordinate_columns = {
        "origin_latitude",
        "origin_longitude",
        "destination_latitude",
        "destination_longitude",
    }
    if not coordinate_columns.issubset(normalized.columns) and not airport_metadata.empty:
        airport_lookup = airport_metadata.set_index("airport_code")
        normalized = normalized.merge(
            airport_lookup[["latitude", "longitude"]].add_prefix("origin_"),
            left_on="origin",
            right_index=True,
            how="left",
        )
        normalized = normalized.merge(
            airport_lookup[["latitude", "longitude"]].add_prefix("destination_"),
            left_on="destination",
            right_index=True,
            how="left",
        )
    if not coordinate_columns.issubset(normalized.columns):
        return pd.DataFrame()
    return normalized.dropna(subset=list(coordinate_columns))


def _draw_europe_basemap(ax) -> None:
    ax.set_facecolor("#d8eef7")
    for coordinates in EUROPE_BASEMAP_POLYGONS:
        ax.add_patch(
            Polygon(
                coordinates,
                closed=True,
                facecolor="#eef1e6",
                edgecolor="#aeb8a6",
                linewidth=0.8,
                alpha=0.96,
                zorder=0,
            )
        )
    ax.text(
        -7.5,
        60.8,
        "North Atlantic",
        color="#6b8794",
        fontsize=9,
        alpha=0.8,
    )
    ax.text(
        11.5,
        55.6,
        "Europe",
        color="#5f6f52",
        fontsize=17,
        fontweight="bold",
        alpha=0.45,
    )
    ax.text(5.0, 36.3, "Mediterranean Sea", color="#6b8794", fontsize=9, alpha=0.8)


def _energy_by_carrier_table(energy_frame: pd.DataFrame, year: int | None) -> pd.DataFrame:
    if energy_frame.empty or year is None:
        return pd.DataFrame()
    selected = energy_frame.loc[pd.to_numeric(energy_frame["year"], errors="coerce").eq(year)]
    if selected.empty:
        return pd.DataFrame()
    primary = (
        selected.groupby("primary_energy_carrier", dropna=False)["primary_energy_consumption"]
        .sum()
        .rename("energy_kwh")
        .reset_index()
        .rename(columns={"primary_energy_carrier": "carrier"})
    )
    secondary = (
        selected.loc[
            selected["secondary_energy_carrier"].fillna("").astype(str).str.strip().ne("")
            & selected["secondary_energy_carrier"].fillna("").astype(str).str.strip().ne("none")
        ]
        .groupby("secondary_energy_carrier", dropna=False)["secondary_energy_consumption"]
        .sum()
        .rename("energy_kwh")
        .reset_index()
        .rename(columns={"secondary_energy_carrier": "carrier"})
    )
    table = pd.concat([primary, secondary], ignore_index=True)
    if table.empty:
        return table
    table = table.groupby("carrier", as_index=False)["energy_kwh"].sum()
    table["energy_twh"] = table["energy_kwh"] / KWH_PER_TWH
    return table.sort_values("energy_kwh", ascending=False)


@solara.component
def _ChartContainer(title: str, content_component):
    with solara.Card(title, style={"padding-bottom": "40px", "margin-bottom": "56px"}):
        content_component()
        solara.HTML(tag="div", unsafe_innerHTML="", style={"height": "40px"})


def _build_model(*, scenario: NATMScenario, seed: int = 42) -> NATMModel:
    return NATMModel(scenario=scenario, seed=seed)


def _single_dashboard_scope(scenario: NATMScenario) -> tuple[str, str]:
    sectors = scenario.enabled_sectors
    if len(sectors) != 1:
        raise ValueError(
            "The common case dashboard currently expects one enabled sector per case.",
        )
    sector_name = sectors[0]
    applications = scenario.applications_for_sector(sector_name)
    if len(applications) != 1:
        raise ValueError(
            "The common case dashboard currently expects one application per case.",
        )
    return sector_name, applications[0]


def _dashboard_title(sector_name: str, application_name: str) -> str:
    return f"NATM {sector_name.title()} {application_name.title()} Dashboard"


def _dashboard_bindings_for_sector(sector_name: str) -> dict[str, object]:
    if sector_name == "aviation":
        return {
            "technology_frame_getter": NATMModel.to_aviation_technology_frame,
            "energy_frame_getter": NATMModel.to_aviation_energy_emissions_frame,
            "investment_frame_getter": NATMModel.to_aviation_investment_frame,
            "stock_count_column": "aircraft_count",
            "stock_axis_label": "Aircraft count",
        }
    if sector_name == "maritime":
        return {
            "technology_frame_getter": NATMModel.to_maritime_technology_frame,
            "energy_frame_getter": NATMModel.to_maritime_energy_emissions_frame,
            "investment_frame_getter": NATMModel.to_maritime_investment_frame,
            "stock_count_column": "vessel_count",
            "stock_axis_label": "Vessel count",
        }
    raise ValueError(f"Unsupported dashboard sector: {sector_name}")


def _available_live_case_names() -> list[str]:
    data_root = PROJECT_ROOT / "data"
    if not data_root.exists():
        return []

    case_names: list[str] = []
    for scenario_path in sorted(data_root.glob("*/scenario.yaml")):
        try:
            scenario = NATMScenario.from_yaml(scenario_path)
            _single_dashboard_scope(scenario)
        except Exception:
            continue
        case_names.append(scenario_path.parent.name)
    return case_names


def build_case_dashboard(
    *,
    case_name: str,
    title: str | None = None,
    sector_name: str | None = None,
    application_name: str | None = None,
    technology_frame_getter=None,
    energy_frame_getter=None,
    investment_frame_getter=None,
    stock_count_column: str | None = None,
    stock_axis_label: str | None = None,
):
    scenario_path = resolve_case_config(case_name)
    scenario = NATMScenario.from_yaml(scenario_path)
    inferred_sector, inferred_application = _single_dashboard_scope(scenario)
    sector_name = sector_name or inferred_sector
    application_name = application_name or inferred_application
    if not scenario.is_application_enabled(sector_name, application_name):
        raise ValueError(
            f"Case '{case_name}' does not enable {sector_name}/{application_name}.",
        )

    bindings = _dashboard_bindings_for_sector(sector_name)
    title = title or _dashboard_title(sector_name, application_name)
    technology_frame_getter = technology_frame_getter or bindings["technology_frame_getter"]
    energy_frame_getter = energy_frame_getter or bindings["energy_frame_getter"]
    investment_frame_getter = investment_frame_getter or bindings["investment_frame_getter"]
    stock_count_column = stock_count_column or str(bindings["stock_count_column"])
    stock_axis_label = stock_axis_label or str(bindings["stock_axis_label"])

    technology_filename = (
        "aviation_technology.csv" if sector_name == "aviation" else "maritime_technology.csv"
    )
    energy_filename = (
        "aviation_energy_emissions.csv"
        if sector_name == "aviation"
        else "maritime_energy_emissions.csv"
    )
    investment_filename = (
        "aviation_investments.csv" if sector_name == "aviation" else "maritime_investments.csv"
    )
    robust_frontier_filename = (
        "aviation_robust_frontier.csv"
        if sector_name == "aviation"
        else "maritime_robust_frontier.csv"
    )

    def _agent_frame(model: NATMModel):
        agent_frame = model.to_agent_frame()
        if agent_frame.empty:
            return agent_frame
        return agent_frame.loc[
            (agent_frame["sector_name"] == sector_name)
            & (agent_frame["application_name"] == application_name)
        ].copy()

    def _technology_frame(model: NATMModel):
        technology_frame = technology_frame_getter(model)
        if technology_frame.empty:
            return technology_frame
        return technology_frame.loc[technology_frame["application_name"] == application_name].copy()

    def _energy_frame(model: NATMModel):
        energy_frame = energy_frame_getter(model)
        if energy_frame.empty:
            return energy_frame
        return energy_frame.loc[energy_frame["application_name"] == application_name].copy()

    def _investment_frame(model: NATMModel):
        investment_frame = investment_frame_getter(model)
        if investment_frame.empty:
            return investment_frame
        return investment_frame.loc[investment_frame["application_name"] == application_name].copy()

    def _robust_frontier_frame(model: NATMModel):
        frontier_frame = model.to_robust_frontier_frame()
        if frontier_frame.empty:
            return frontier_frame
        return frontier_frame.loc[
            (frontier_frame["sector_name"] == sector_name)
            & (frontier_frame["application_name"] == application_name)
        ].copy()

    def _live_result_frames(model: NATMModel) -> dict[str, pd.DataFrame]:
        return {
            "summary": model.to_frame(),
            "agents": _agent_frame(model),
            "technology": _technology_frame(model),
            "energy": _energy_frame(model),
            "investments": _investment_frame(model),
            "robust_frontier": _robust_frontier_frame(model),
        }

    def _load_aviation_preprocessing_frames() -> dict[str, pd.DataFrame]:
        if sector_name != "aviation":
            return {}
        preprocessing_config = scenario.aviation_preprocessing_config()
        airport_metadata_path = None
        if preprocessing_config is not None:
            airport_metadata_path = preprocessing_config.resolve_path(
                scenario.base_path,
                "airport_metadata",
            )
        if airport_metadata_path is None:
            airport_metadata_path = (
                PROJECT_ROOT
                / "data"
                / "examples"
                / "aviation_preprocessing"
                / "airports_sample.csv"
            )
        return {
            "airport_metadata": _normalize_airport_metadata(
                _read_csv_if_exists(airport_metadata_path),
            ),
            "enriched_stock": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "aviation_fleet_stock_enriched.csv",
            ),
            "matching_report": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "aviation_stock_matching_report.csv",
            ),
            "activity_profiles": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "aviation_activity_profiles.csv",
            ),
            "airport_allocation": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "aviation_airport_allocation.csv",
            ),
            "calibration_targets": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "aviation_calibration_targets.csv",
            ),
            "openap_flights": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "openap_flight_fuel_emissions.csv",
            ),
            "openap_type_summary": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "openap_aircraft_type_summary.csv",
            ),
            "openap_route_summary": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "openap_route_summary.csv",
            ),
            "openap_mapping_log": _read_csv_if_exists(
                PROCESSED_AVIATION_ROOT / "openap_aircraft_type_mapping_log.csv",
            ),
        }

    def _available_result_folders() -> list[str]:
        if not RESULTS_ROOT.exists():
            return []
        compatible_folders: list[str] = []
        for path in sorted(RESULTS_ROOT.iterdir()):
            if not path.is_dir():
                continue
            required_files = [
                path / "model_summary.csv",
                path / "agents.csv",
                path / technology_filename,
                path / energy_filename,
                path / investment_filename,
            ]
            if all(file_path.exists() for file_path in required_files):
                compatible_folders.append(path.name)
        return compatible_folders

    def _load_result_frames(folder_name: str | None) -> dict[str, pd.DataFrame]:
        empty_frames = {
            "summary": pd.DataFrame(),
            "agents": pd.DataFrame(),
            "technology": pd.DataFrame(),
            "energy": pd.DataFrame(),
            "investments": pd.DataFrame(),
            "robust_frontier": pd.DataFrame(),
            "airport_fuel_demand": pd.DataFrame(),
            "route_energy_flow": pd.DataFrame(),
        }
        if not folder_name:
            return empty_frames

        result_dir = RESULTS_ROOT / folder_name
        if not result_dir.exists():
            return empty_frames

        return {
            "summary": pd.read_csv(result_dir / "model_summary.csv"),
            "agents": pd.read_csv(result_dir / "agents.csv"),
            "technology": pd.read_csv(result_dir / technology_filename),
            "energy": pd.read_csv(result_dir / energy_filename),
            "investments": pd.read_csv(result_dir / investment_filename),
            "robust_frontier": _filter_application(
                _read_csv_if_exists(result_dir / robust_frontier_filename),
                application_name,
            ),
            "airport_fuel_demand": _read_csv_if_exists(result_dir / "airport_fuel_demand.csv"),
            "route_energy_flow": _read_csv_if_exists(result_dir / "route_energy_flow.csv"),
        }

    @solara.component
    def LatestSummary(model: NATMModel):
        update_counter.get()
        summary_frame = model.to_frame()
        agent_frame = _agent_frame(model)
        if summary_frame.empty:
            solara.Markdown("No model summary is available yet.")
            return

        latest = summary_frame.iloc[-1]
        year = int(latest["year"])
        alternative_share = float(latest[f"{sector_name}_alternative_share"])
        transition_pressure = float(latest[f"{sector_name}_transition_pressure"])
        carbon_price = float(latest["carbon_price"])
        operator_count = int(agent_frame["operator_name"].nunique()) if not agent_frame.empty else 0
        total_assets = (
            int(agent_frame.loc[agent_frame["year"] == year, "total_assets"].sum())
            if not agent_frame.empty
            else 0
        )

        solara.Markdown(
            "\n".join(
                [
                    f"### {title} Snapshot ({year})",
                    f"- Alternative share: `{alternative_share:.2%}`",
                    f"- Transition pressure: `{transition_pressure:.2%}`",
                    f"- Carbon price: `{carbon_price:.2f}`",
                    f"- Operators: `{operator_count}`",
                    f"- Total fleet stock: `{total_assets}`",
                    f"- Case: `{case_name}`",
                ],
            ),
        )

    @solara.component
    def OperatorShares(model: NATMModel):
        @solara.component
        def _content():
            update_counter.get()
            agent_frame = _agent_frame(model)
            available_years = (
                sorted(agent_frame["year"].astype(int).unique().tolist())
                if not agent_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else model.current_year,
            )
            if agent_frame.empty:
                solara.Markdown(f"No {title.lower()} agent data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Operator shares year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = agent_frame.loc[agent_frame["year"] == effective_year].copy()
            selected = selected.sort_values("alternative_share", ascending=True)

            fig = Figure(figsize=(8.6, 5.3))
            ax = fig.subplots()
            ax.barh(
                selected["operator_name"].astype(str),
                selected["alternative_share"].astype(float),
                color="#2a6f97",
            )
            ax.set_xlim(0.0, 1.0)
            ax.set_xlabel("Alternative share")
            ax.set_title(f"{title} Operator Shares ({effective_year})")
            ax.grid(axis="x", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Operator Shares", _content)

    @solara.component
    def TechnologyMix(model: NATMModel):
        @solara.component
        def _content():
            update_counter.get()
            technology_frame = _technology_frame(model)
            available_years = (
                sorted(technology_frame["year"].astype(int).unique().tolist())
                if not technology_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else model.current_year,
            )
            if technology_frame.empty:
                solara.Markdown(f"No {title.lower()} technology data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Technology mix year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = technology_frame.loc[technology_frame["year"] == effective_year].copy()
            selected = (
                selected.groupby("current_technology", as_index=False)[stock_count_column]
                .sum()
                .sort_values(stock_count_column, ascending=False)
            )

            positions = list(range(len(selected)))
            fig = Figure(figsize=(8.6, 5.6))
            ax = fig.subplots()
            ax.bar(
                positions,
                selected[stock_count_column].astype(float),
                color="#386641",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                selected["current_technology"].astype(str).tolist(),
                rotation=32,
                ha="right",
            )
            ax.set_ylabel(stock_axis_label)
            ax.set_title(f"{title} Technology Mix ({effective_year})")
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Technology Mix", _content)

    @solara.component
    def EnergyByCarrier(model: NATMModel):
        @solara.component
        def _content():
            update_counter.get()
            energy_frame = _energy_frame(model)
            available_years = (
                sorted(energy_frame["year"].astype(int).unique().tolist())
                if not energy_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else model.current_year,
            )
            if energy_frame.empty:
                solara.Markdown(f"No {title.lower()} energy data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Energy by carrier year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = energy_frame.loc[energy_frame["year"] == effective_year].copy()

            primary = (
                selected.groupby("primary_energy_carrier", dropna=False)[
                    "primary_energy_consumption"
                ]
                .sum()
                .rename("energy")
                .reset_index()
                .rename(columns={"primary_energy_carrier": "carrier"})
            )
            secondary = (
                selected.loc[
                    selected["secondary_energy_carrier"].fillna("").astype(str).str.strip().ne("")
                    & selected["secondary_energy_carrier"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .ne("none")
                ]
                .groupby("secondary_energy_carrier", dropna=False)["secondary_energy_consumption"]
                .sum()
                .rename("energy")
                .reset_index()
                .rename(columns={"secondary_energy_carrier": "carrier"})
            )
            carrier_frame = (
                primary.groupby("carrier", as_index=False)["energy"].sum()
                if secondary.empty
                else pd.concat([primary, secondary], ignore_index=True)
                .groupby(
                    "carrier",
                    as_index=False,
                )["energy"]
                .sum()
            )
            carrier_frame["energy_twh"] = carrier_frame["energy"].astype(float) / KWH_PER_TWH
            carrier_frame = carrier_frame.sort_values("energy", ascending=False)

            positions = list(range(len(carrier_frame)))
            fig = Figure(figsize=(8.6, 5.5))
            ax = fig.subplots()
            ax.bar(
                positions,
                carrier_frame["energy_twh"].astype(float),
                color="#9c6644",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                carrier_frame["carrier"].astype(str).tolist(),
                rotation=30,
                ha="right",
            )
            ax.set_ylabel("Energy consumption (TWh)")
            ax.set_title(f"{title} Energy by Carrier ({effective_year})")
            ax.yaxis.set_major_formatter(_decimal_formatter(3, " TWh"))
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Energy by Carrier", _content)

    @solara.component
    def EmissionsOverviewContent(
        frames: dict[str, pd.DataFrame],
        source_label: str,
        default_year: int,
    ):
        energy_frame = frames.get("energy", pd.DataFrame())
        if not energy_frame.empty:
            energy_frame = _filter_application(energy_frame, application_name)

        openap_flights = pd.DataFrame()
        if sector_name == "aviation":
            openap_flights = _load_aviation_preprocessing_frames().get(
                "openap_flights",
                pd.DataFrame(),
            )
            if not openap_flights.empty and "application_name" in openap_flights.columns:
                openap_flights = _filter_application(openap_flights, application_name)

        datasets: dict[str, pd.DataFrame] = {}
        if _emission_columns(energy_frame):
            datasets["Simulation emissions"] = energy_frame
        if _emission_columns(openap_flights):
            datasets["OpenAP pollutants"] = openap_flights

        if not datasets:
            solara.Markdown("No emissions or pollutant columns are available for this dashboard.")
            return

        dataset_options = list(datasets)
        selected_dataset, set_selected_dataset = solara.use_state(dataset_options[0])
        effective_dataset = (
            selected_dataset if selected_dataset in dataset_options else dataset_options[0]
        )
        frame = datasets[effective_dataset].copy()
        emission_columns = _emission_columns(frame)
        available_years = (
            sorted(frame["year"].dropna().astype(int).unique().tolist())
            if "year" in frame.columns
            else []
        )
        selected_year, set_selected_year = solara.use_state(
            available_years[-1] if available_years else default_year,
        )
        effective_year = (
            (selected_year if selected_year in available_years else available_years[-1])
            if available_years
            else None
        )
        selected_pollutant, set_selected_pollutant = solara.use_state(emission_columns[0])
        effective_pollutant = (
            selected_pollutant if selected_pollutant in emission_columns else emission_columns[0]
        )

        solara.Markdown(f"### Emissions ({source_label})")
        if len(dataset_options) > 1:
            solara.ToggleButtonsSingle(
                value=effective_dataset,
                values=dataset_options,
                on_value=set_selected_dataset,
            )
        if available_years:
            solara.SliderInt(
                "Emissions year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
        solara.Select(
            "Pollutant breakdown",
            values=emission_columns,
            value=effective_pollutant,
            on_value=set_selected_pollutant,
        )

        selected_frame = frame
        if effective_year is not None and "year" in selected_frame.columns:
            selected_frame = selected_frame.loc[
                selected_frame["year"].astype(int).eq(effective_year)
            ].copy()
        if selected_frame.empty:
            solara.Markdown("No emissions rows are available for this selection.")
            return

        totals = _emission_totals_table(selected_frame, emission_columns)
        positions = list(range(len(totals)))
        fig = Figure(figsize=(8.8, 5.4))
        ax = fig.subplots()
        ax.bar(
            positions,
            totals["emissions_tonnes"].astype(float),
            color="#6a994e",
        )
        ax.set_xticks(positions)
        ax.set_xticklabels(totals["pollutant"].astype(str).tolist(), rotation=25, ha="right")
        ax.set_ylabel("Emissions (tonnes)")
        title_year = f" ({effective_year})" if effective_year is not None else ""
        ax.set_title(f"{title} Emissions by Pollutant{title_year}")
        ax.yaxis.set_major_formatter(_compact_number_formatter(" t"))
        ax.grid(axis="y", alpha=0.25)
        _show_figure(fig)

        breakdown_key = next(
            (
                column
                for column in ("operator_name", "route", "origin", "current_technology")
                if column in selected_frame.columns
            ),
            None,
        )
        selected_frame[effective_pollutant] = pd.to_numeric(
            selected_frame[effective_pollutant],
            errors="coerce",
        ).fillna(0.0)
        if breakdown_key is not None:
            breakdown = (
                selected_frame.groupby(breakdown_key, dropna=False, as_index=False)[
                    effective_pollutant
                ]
                .sum()
                .rename(
                    columns={
                        breakdown_key: "group",
                        effective_pollutant: "emissions_kg",
                    }
                )
            )
            breakdown["pollutant"] = _emission_label(effective_pollutant)
            breakdown["emissions_tonnes"] = breakdown["emissions_kg"] / EMISSION_KG_TO_TONNES
            breakdown = breakdown.sort_values("emissions_tonnes", ascending=False)
            solara.Markdown(f"#### {_emission_label(effective_pollutant)} Breakdown")
            _show_dataframe(
                breakdown[["group", "pollutant", "emissions_tonnes"]],
                max_rows=16,
            )

        solara.Markdown("#### Pollutant Totals")
        _show_dataframe(totals, max_rows=len(totals))

    @solara.component
    def EmissionsOverview(model: NATMModel):
        update_counter.get()
        with solara.Card("Emissions", style={"margin-bottom": "28px"}):
            EmissionsOverviewContent(
                _live_result_frames(model),
                "live case",
                model.current_year,
            )

    @solara.component
    def InvestmentsByOperator(model: NATMModel):
        @solara.component
        def _content():
            update_counter.get()
            investment_frame = _investment_frame(model)
            available_years = (
                sorted(investment_frame["year"].astype(int).unique().tolist())
                if not investment_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else model.current_year,
            )
            if investment_frame.empty:
                solara.Markdown(f"No {title.lower()} investment data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Investments year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = investment_frame.loc[investment_frame["year"] == effective_year].copy()
            selected = (
                selected.groupby("operator_name", as_index=False)["investment_cost_eur"]
                .sum()
                .sort_values("investment_cost_eur", ascending=False)
            )

            positions = list(range(len(selected)))
            fig = Figure(figsize=(8.6, 5.5))
            ax = fig.subplots()
            ax.bar(
                positions,
                selected["investment_cost_eur"].astype(float),
                color="#bc4749",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                selected["operator_name"].astype(str).tolist(),
                rotation=30,
                ha="right",
            )
            ax.set_ylabel("Investment cost (EUR)")
            ax.set_title(f"{title} Investments by Operator ({effective_year})")
            ax.yaxis.set_major_formatter(_compact_number_formatter(" EUR"))
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Investments by Operator", _content)

    @solara.component
    def SavedLatestSummary(folder_name: str):
        frames = _load_result_frames(folder_name)
        summary_frame = frames["summary"]
        agent_frame = frames["agents"]
        if not agent_frame.empty:
            agent_frame = agent_frame.loc[
                (agent_frame["sector_name"] == sector_name)
                & (agent_frame["application_name"] == application_name)
            ].copy()
        if summary_frame.empty:
            solara.Markdown("No saved model summary is available for this results folder.")
            return

        latest = summary_frame.iloc[-1]
        year = int(latest["year"])
        alternative_share = float(latest[f"{sector_name}_alternative_share"])
        transition_pressure = float(latest[f"{sector_name}_transition_pressure"])
        carbon_price = float(latest["carbon_price"])
        operator_count = int(agent_frame["operator_name"].nunique()) if not agent_frame.empty else 0
        total_assets = (
            int(agent_frame.loc[agent_frame["year"] == year, "total_assets"].sum())
            if not agent_frame.empty
            else 0
        )

        solara.Markdown(
            "\n".join(
                [
                    f"### {title} Snapshot ({year})",
                    f"- Alternative share: `{alternative_share:.2%}`",
                    f"- Transition pressure: `{transition_pressure:.2%}`",
                    f"- Carbon price: `{carbon_price:.2f}`",
                    f"- Operators: `{operator_count}`",
                    f"- Total fleet stock: `{total_assets}`",
                    f"- Source: `simulation_results/{folder_name}`",
                ],
            ),
        )

    @solara.component
    def SavedOperatorShares(folder_name: str):
        @solara.component
        def _content():
            agent_frame = _load_result_frames(folder_name)["agents"]
            if not agent_frame.empty:
                agent_frame = agent_frame.loc[
                    (agent_frame["sector_name"] == sector_name)
                    & (agent_frame["application_name"] == application_name)
                ].copy()
            available_years = (
                sorted(agent_frame["year"].astype(int).unique().tolist())
                if not agent_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else scenario.end_year,
            )
            if agent_frame.empty:
                solara.Markdown(f"No saved {title.lower()} agent data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Operator shares year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = agent_frame.loc[agent_frame["year"] == effective_year].copy()
            selected = selected.sort_values("alternative_share", ascending=True)

            fig = Figure(figsize=(8.6, 5.3))
            ax = fig.subplots()
            ax.barh(
                selected["operator_name"].astype(str),
                selected["alternative_share"].astype(float),
                color="#2a6f97",
            )
            ax.set_xlim(0.0, 1.0)
            ax.set_xlabel("Alternative share")
            ax.set_title(f"{title} Operator Shares ({effective_year})")
            ax.grid(axis="x", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Operator Shares", _content)

    @solara.component
    def SavedTechnologyMix(folder_name: str):
        @solara.component
        def _content():
            technology_frame = _load_result_frames(folder_name)["technology"]
            if not technology_frame.empty:
                technology_frame = technology_frame.loc[
                    technology_frame["application_name"] == application_name
                ].copy()
            available_years = (
                sorted(technology_frame["year"].astype(int).unique().tolist())
                if not technology_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else scenario.end_year,
            )
            if technology_frame.empty:
                solara.Markdown(f"No saved {title.lower()} technology data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Technology mix year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = technology_frame.loc[technology_frame["year"] == effective_year].copy()
            selected = (
                selected.groupby("current_technology", as_index=False)[stock_count_column]
                .sum()
                .sort_values(stock_count_column, ascending=False)
            )

            positions = list(range(len(selected)))
            fig = Figure(figsize=(8.6, 5.6))
            ax = fig.subplots()
            ax.bar(
                positions,
                selected[stock_count_column].astype(float),
                color="#386641",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                selected["current_technology"].astype(str).tolist(),
                rotation=32,
                ha="right",
            )
            ax.set_ylabel(stock_axis_label)
            ax.set_title(f"{title} Technology Mix ({effective_year})")
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Technology Mix", _content)

    @solara.component
    def SavedEnergyByCarrier(folder_name: str):
        @solara.component
        def _content():
            energy_frame = _load_result_frames(folder_name)["energy"]
            if not energy_frame.empty:
                energy_frame = energy_frame.loc[
                    energy_frame["application_name"] == application_name
                ].copy()
            available_years = (
                sorted(energy_frame["year"].astype(int).unique().tolist())
                if not energy_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else scenario.end_year,
            )
            if energy_frame.empty:
                solara.Markdown(f"No saved {title.lower()} energy data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Energy by carrier year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = energy_frame.loc[energy_frame["year"] == effective_year].copy()

            primary = (
                selected.groupby("primary_energy_carrier", dropna=False)[
                    "primary_energy_consumption"
                ]
                .sum()
                .rename("energy")
                .reset_index()
                .rename(columns={"primary_energy_carrier": "carrier"})
            )
            secondary = (
                selected.loc[
                    selected["secondary_energy_carrier"].fillna("").astype(str).str.strip().ne("")
                    & selected["secondary_energy_carrier"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .ne("none")
                ]
                .groupby("secondary_energy_carrier", dropna=False)["secondary_energy_consumption"]
                .sum()
                .rename("energy")
                .reset_index()
                .rename(columns={"secondary_energy_carrier": "carrier"})
            )
            carrier_frame = (
                primary.groupby("carrier", as_index=False)["energy"].sum()
                if secondary.empty
                else pd.concat([primary, secondary], ignore_index=True)
                .groupby(
                    "carrier",
                    as_index=False,
                )["energy"]
                .sum()
            )
            carrier_frame["energy_twh"] = carrier_frame["energy"].astype(float) / KWH_PER_TWH
            carrier_frame = carrier_frame.sort_values("energy", ascending=False)

            positions = list(range(len(carrier_frame)))
            fig = Figure(figsize=(8.6, 5.5))
            ax = fig.subplots()
            ax.bar(
                positions,
                carrier_frame["energy_twh"].astype(float),
                color="#9c6644",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                carrier_frame["carrier"].astype(str).tolist(),
                rotation=30,
                ha="right",
            )
            ax.set_ylabel("Energy consumption (TWh)")
            ax.set_title(f"{title} Energy by Carrier ({effective_year})")
            ax.yaxis.set_major_formatter(_decimal_formatter(3, " TWh"))
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Energy by Carrier", _content)

    @solara.component
    def SavedEmissionsOverview(folder_name: str):
        with solara.Card("Emissions", style={"margin-bottom": "28px"}):
            EmissionsOverviewContent(
                _load_result_frames(folder_name),
                f"saved: {folder_name}",
                scenario.end_year,
            )

    @solara.component
    def SavedInvestmentsByOperator(folder_name: str):
        @solara.component
        def _content():
            investment_frame = _load_result_frames(folder_name)["investments"]
            if not investment_frame.empty:
                investment_frame = investment_frame.loc[
                    investment_frame["application_name"] == application_name
                ].copy()
            available_years = (
                sorted(investment_frame["year"].astype(int).unique().tolist())
                if not investment_frame.empty
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else scenario.end_year,
            )
            if investment_frame.empty:
                solara.Markdown(f"No saved {title.lower()} investment data is available yet.")
                return

            effective_year = (
                selected_year if selected_year in available_years else available_years[-1]
            )
            solara.SliderInt(
                "Investments year",
                value=effective_year,
                min=available_years[0],
                max=available_years[-1],
                step=1,
                on_value=set_selected_year,
            )
            selected = investment_frame.loc[investment_frame["year"] == effective_year].copy()
            selected = (
                selected.groupby("operator_name", as_index=False)["investment_cost_eur"]
                .sum()
                .sort_values("investment_cost_eur", ascending=False)
            )

            positions = list(range(len(selected)))
            fig = Figure(figsize=(8.6, 5.5))
            ax = fig.subplots()
            ax.bar(
                positions,
                selected["investment_cost_eur"].astype(float),
                color="#bc4749",
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(
                selected["operator_name"].astype(str).tolist(),
                rotation=30,
                ha="right",
            )
            ax.set_ylabel("Investment cost (EUR)")
            ax.set_title(f"{title} Investments by Operator ({effective_year})")
            ax.yaxis.set_major_formatter(_compact_number_formatter(" EUR"))
            ax.grid(axis="y", alpha=0.25)
            _show_figure(fig)

        _ChartContainer("Investments by Operator", _content)

    @solara.component
    def RobustFrontierContent(frames: dict[str, pd.DataFrame], source_label: str):
        frontier = frames.get("robust_frontier", pd.DataFrame())
        required_columns = {
            "year",
            "operator_name",
            "segment",
            "decision_attitude",
            "candidate_technology",
            "selected_technology",
            "expected_utility",
            "robust_score",
            "selected_flag",
        }
        if frontier.empty or not required_columns.issubset(frontier.columns):
            solara.Markdown("No robust frontier output is available for this source.")
            return

        frontier = frontier.copy()
        for column in (
            "year",
            "expected_utility",
            "robust_score",
            "worst_case_utility",
            "expected_shortfall_utility",
            "worst_case_expected_shortfall_utility",
            "candidate_utility",
            "scenario_probability",
        ):
            if column in frontier.columns:
                frontier[column] = pd.to_numeric(frontier[column], errors="coerce")
        frontier["selected_flag"] = (
            frontier["selected_flag"].astype(str).str.lower().isin({"true", "1", "yes"})
        )
        years = sorted(frontier["year"].dropna().astype(int).unique().tolist())
        operators = sorted(frontier["operator_name"].dropna().astype(str).unique().tolist())
        segments = sorted(frontier["segment"].dropna().astype(str).unique().tolist())
        attitudes = sorted(frontier["decision_attitude"].dropna().astype(str).unique().tolist())

        selected_year, set_selected_year = solara.use_state(years[-1] if years else None)
        selected_operator, set_selected_operator = solara.use_state("All")
        selected_segment, set_selected_segment = solara.use_state("All")
        selected_attitude, set_selected_attitude = solara.use_state("All")
        selected_asset, set_selected_asset = solara.use_state("All")
        if not years:
            solara.Markdown("Robust frontier output has no year values.")
            return

        effective_year = selected_year if selected_year in years else years[-1]
        solara.Markdown(f"### Robust Frontier ({source_label})")
        solara.SliderInt(
            "Decision year",
            value=effective_year,
            min=years[0],
            max=years[-1],
            step=1,
            on_value=set_selected_year,
        )
        solara.Select(
            "Operator",
            values=["All", *operators],
            value=selected_operator if selected_operator in operators else "All",
            on_value=set_selected_operator,
        )
        solara.Select(
            "Segment",
            values=["All", *segments],
            value=selected_segment if selected_segment in segments else "All",
            on_value=set_selected_segment,
        )
        solara.Select(
            "Decision attitude",
            values=["All", *attitudes],
            value=selected_attitude if selected_attitude in attitudes else "All",
            on_value=set_selected_attitude,
        )

        filtered = frontier.loc[frontier["year"].eq(effective_year)].copy()
        if selected_operator in operators:
            filtered = filtered.loc[filtered["operator_name"].astype(str).eq(selected_operator)]
        if selected_segment in segments:
            filtered = filtered.loc[filtered["segment"].astype(str).eq(selected_segment)]
        if selected_attitude in attitudes:
            filtered = filtered.loc[filtered["decision_attitude"].astype(str).eq(selected_attitude)]

        asset_column = "asset_id" if "asset_id" in filtered.columns else ""
        asset_label = "Aircraft" if sector_name == "aviation" else "Vessel"
        asset_options = (
            sorted(filtered[asset_column].dropna().astype(str).unique().tolist())
            if asset_column
            else []
        )
        effective_asset = selected_asset if selected_asset in asset_options else "All"
        solara.Select(
            asset_label,
            values=["All", *asset_options],
            value=effective_asset,
            on_value=set_selected_asset,
        )
        if effective_asset in asset_options:
            filtered = filtered.loc[filtered[asset_column].astype(str).eq(effective_asset)]

        if filtered.empty:
            solara.Markdown("No robust frontier rows match the selected filters.")
            return

        decision_keys = [
            column
            for column in (
                "year",
                "operator_name",
                "asset_id",
                "segment",
                "decision_attitude",
                "candidate_technology",
            )
            if column in filtered.columns
        ]
        candidate_frame = filtered.drop_duplicates(subset=decision_keys)
        aggregation = {
            "expected_utility": ("expected_utility", "mean"),
            "robust_score": ("robust_score", "mean"),
            "selected_flag": ("selected_flag", "max"),
        }
        for optional_column in (
            "worst_case_utility",
            "expected_shortfall_utility",
            "worst_case_expected_shortfall_utility",
        ):
            if optional_column in candidate_frame.columns:
                aggregation[optional_column] = (optional_column, "mean")
        candidate_summary = (
            candidate_frame.groupby("candidate_technology", as_index=False)
            .agg(**aggregation)
            .sort_values("robust_score", ascending=False)
        )

        x_metric = (
            "worst_case_utility"
            if "worst_case_utility" in candidate_summary.columns
            else ("expected_utility")
        )
        y_metric = (
            "worst_case_expected_shortfall_utility"
            if "worst_case_expected_shortfall_utility" in candidate_summary.columns
            else "robust_score"
        )
        uses_robust_frontier_axes = (
            x_metric == "worst_case_utility" and y_metric == "worst_case_expected_shortfall_utility"
        )
        frontier_points = candidate_summary.dropna(subset=[x_metric, y_metric]).copy()
        if not frontier_points.empty:
            solara.Markdown("#### Robust Frontier")
            fig = Figure(figsize=(8.8, 6.0))
            ax = fig.subplots()
            point_palette = ["#2a6f97", "#bc4749", "#386641", "#6a4c93", "#f4a261", "#457b9d"]
            for point_index, row in enumerate(frontier_points.itertuples(index=False)):
                selected = bool(row.selected_flag)
                color = "#bc4749" if selected else point_palette[point_index % len(point_palette)]
                marker = "*" if selected else "o"
                size = 170 if selected else 85
                x_value = float(getattr(row, x_metric))
                y_value = float(getattr(row, y_metric))
                technology = str(row.candidate_technology)
                ax.scatter(
                    [x_value],
                    [y_value],
                    s=size,
                    marker=marker,
                    color=color,
                    edgecolors="#222222",
                    linewidths=0.7,
                    zorder=3,
                )
                label = f"{technology}\nselected" if selected else technology
                ax.annotate(
                    label,
                    xy=(x_value, y_value),
                    xytext=(9, 9),
                    textcoords="offset points",
                    fontsize=8,
                    arrowprops={"arrowstyle": "-", "color": color, "linewidth": 0.8},
                )

            x_values = frontier_points[x_metric].astype(float)
            y_values = frontier_points[y_metric].astype(float)
            x_span = float(x_values.max() - x_values.min())
            y_span = float(y_values.max() - y_values.min())
            x_padding = max(x_span * 0.12, 0.05)
            y_padding = max(y_span * 0.12, 0.05)
            ax.set_xlim(float(x_values.min()) - x_padding, float(x_values.max()) + x_padding)
            ax.set_ylim(float(y_values.min()) - y_padding, float(y_values.max()) + y_padding)
            x_label = (
                "Worst-case mean utility"
                if x_metric == "worst_case_utility"
                else ("Expected utility")
            )
            y_label = (
                "Worst-case expected shortfall utility"
                if y_metric == "worst_case_expected_shortfall_utility"
                else "Expected shortfall utility"
                if y_metric == "expected_shortfall_utility"
                else "Robust score"
            )
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            asset_title = f" - {asset_label} {effective_asset}" if effective_asset != "All" else ""
            title_prefix = (
                "Robust Frontier: Worst-case ES vs Worst-case Mean"
                if uses_robust_frontier_axes
                else "Robust Frontier (higher is better)"
            )
            ax.set_title(f"{title_prefix}{asset_title}")
            ax.grid(alpha=0.25)
            _show_figure(fig)

        solara.Markdown("#### Candidate Utility Summary")
        positions = list(range(len(candidate_summary)))
        fig = Figure(figsize=(8.8, 5.2))
        ax = fig.subplots()
        width = 0.36
        expected_colors = [
            "#2a6f97" if not selected else "#1b4332"
            for selected in candidate_summary["selected_flag"]
        ]
        robust_colors = [
            "#f4a261" if not selected else "#bc4749"
            for selected in candidate_summary["selected_flag"]
        ]
        ax.bar(
            [position - width / 2 for position in positions],
            candidate_summary["expected_utility"].astype(float),
            width=width,
            label="Expected utility",
            color=expected_colors,
        )
        ax.bar(
            [position + width / 2 for position in positions],
            candidate_summary["robust_score"].astype(float),
            width=width,
            label="Robust score",
            color=robust_colors,
        )
        ax.set_xticks(positions)
        ax.set_xticklabels(
            candidate_summary["candidate_technology"].astype(str).tolist(),
            rotation=30,
            ha="right",
        )
        ax.set_ylabel("Utility score")
        ax.set_title(f"{title} Candidate Frontier ({effective_year})")
        ax.grid(axis="y", alpha=0.25)
        ax.legend()
        _show_figure(fig)

        selected_rows = frontier.loc[frontier["selected_flag"]].copy()
        selected_keys = [
            column
            for column in (
                "year",
                "operator_name",
                "asset_id",
                "segment",
                "decision_attitude",
                "selected_technology",
            )
            if column in selected_rows.columns
        ]
        selected_rows = selected_rows.drop_duplicates(subset=selected_keys)
        share_frame = (
            selected_rows.groupby(
                ["year", "decision_attitude", "selected_technology"],
                as_index=False,
            )
            .size()
            .rename(columns={"size": "selected_count"})
        )
        if not share_frame.empty:
            totals = share_frame.groupby(["year", "decision_attitude"])["selected_count"].transform(
                "sum",
            )
            share_frame["share"] = share_frame["selected_count"] / totals.clip(lower=1)
            x_keys = (
                share_frame[["year", "decision_attitude"]]
                .drop_duplicates()
                .sort_values(["year", "decision_attitude"])
            )
            x_labels = [
                f"{int(row.year)}\n{row.decision_attitude}"
                for row in x_keys.itertuples(index=False)
            ]
            technologies = sorted(share_frame["selected_technology"].astype(str).unique())
            palette = ["#386641", "#2a6f97", "#bc4749", "#9c6644", "#6a4c93", "#457b9d"]
            fig = Figure(figsize=(9.2, 5.4))
            ax = fig.subplots()
            bottoms = [0.0 for _ in x_labels]
            for tech_index, technology in enumerate(technologies):
                values = []
                for row in x_keys.itertuples(index=False):
                    mask = (
                        share_frame["year"].eq(row.year)
                        & share_frame["decision_attitude"].eq(row.decision_attitude)
                        & share_frame["selected_technology"].astype(str).eq(technology)
                    )
                    values.append(float(share_frame.loc[mask, "share"].sum()))
                ax.bar(
                    list(range(len(x_labels))),
                    values,
                    bottom=bottoms,
                    label=technology,
                    color=palette[tech_index % len(palette)],
                )
                bottoms = [bottom + value for bottom, value in zip(bottoms, values, strict=False)]
            ax.set_xticks(list(range(len(x_labels))))
            ax.set_xticklabels(x_labels, rotation=0)
            ax.set_ylim(0.0, 1.0)
            ax.set_ylabel("Selected technology share")
            ax.set_title(f"{title} Selected Technology Shares by Attitude")
            ax.grid(axis="y", alpha=0.25)
            ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0))
            _show_figure(fig)

        table_columns = [
            column
            for column in (
                "candidate_technology",
                "expected_utility",
                "robust_score",
                "selected_flag",
            )
            if column in candidate_summary.columns
        ]
        solara.Markdown("#### Candidate Scores")
        _show_dataframe(candidate_summary[table_columns], max_rows=16)

    @solara.component
    def RobustFrontier(model: NATMModel):
        update_counter.get()
        with solara.Card("Robust Frontier", style={"margin-bottom": "28px"}):
            RobustFrontierContent(_live_result_frames(model), "live case")

    @solara.component
    def SavedRobustFrontier(folder_name: str):
        with solara.Card("Robust Frontier", style={"margin-bottom": "28px"}):
            RobustFrontierContent(_load_result_frames(folder_name), f"saved: {folder_name}")

    @solara.component
    def OperatorDrilldownContent(frames: dict[str, pd.DataFrame], source_label: str):
        agent_frame = frames.get("agents", pd.DataFrame())
        technology_frame = frames.get("technology", pd.DataFrame())
        energy_frame = frames.get("energy", pd.DataFrame())
        investment_frame = frames.get("investments", pd.DataFrame())

        operator_sources = [
            frame["operator_name"].dropna().astype(str)
            for frame in (agent_frame, technology_frame, energy_frame, investment_frame)
            if not frame.empty and "operator_name" in frame.columns
        ]
        operators = sorted(set(pd.concat(operator_sources).str.strip())) if operator_sources else []
        operators = [operator for operator in operators if operator]
        selected_operator, set_selected_operator = solara.use_state(
            operators[0] if operators else "",
        )
        if not operators:
            solara.Markdown(f"No {title.lower()} operator data is available for drill-down.")
            return

        effective_operator = selected_operator if selected_operator in operators else operators[0]
        solara.Select(
            "Operator",
            values=operators,
            value=effective_operator,
            on_value=set_selected_operator,
        )

        operator_agents = (
            agent_frame.loc[agent_frame["operator_name"].astype(str).eq(effective_operator)].copy()
            if not agent_frame.empty and "operator_name" in agent_frame.columns
            else pd.DataFrame()
        )
        operator_technology = (
            technology_frame.loc[
                technology_frame["operator_name"].astype(str).eq(effective_operator)
            ].copy()
            if not technology_frame.empty and "operator_name" in technology_frame.columns
            else pd.DataFrame()
        )
        operator_energy = (
            energy_frame.loc[
                energy_frame["operator_name"].astype(str).eq(effective_operator)
            ].copy()
            if not energy_frame.empty and "operator_name" in energy_frame.columns
            else pd.DataFrame()
        )
        operator_investments = (
            investment_frame.loc[
                investment_frame["operator_name"].astype(str).eq(effective_operator)
            ].copy()
            if not investment_frame.empty and "operator_name" in investment_frame.columns
            else pd.DataFrame()
        )

        latest_year = (
            _latest_year(operator_agents)
            or _latest_year(operator_technology)
            or _latest_year(operator_energy)
            or _latest_year(operator_investments)
        )
        latest_agents = (
            operator_agents.loc[
                pd.to_numeric(operator_agents["year"], errors="coerce").eq(latest_year)
            ]
            if latest_year is not None and not operator_agents.empty
            else pd.DataFrame()
        )
        latest_assets = (
            int(pd.to_numeric(latest_agents["total_assets"], errors="coerce").sum())
            if not latest_agents.empty and "total_assets" in latest_agents.columns
            else 0
        )
        latest_alternative_share = (
            float(pd.to_numeric(latest_agents["alternative_share"], errors="coerce").mean())
            if not latest_agents.empty and "alternative_share" in latest_agents.columns
            else 0.0
        )
        total_investment = (
            float(pd.to_numeric(operator_investments["investment_cost_eur"], errors="coerce").sum())
            if not operator_investments.empty
            and "investment_cost_eur" in operator_investments.columns
            else 0.0
        )
        total_energy_twh = 0.0
        if not operator_energy.empty:
            total_energy_twh = (
                pd.to_numeric(
                    operator_energy.get("primary_energy_consumption", pd.Series(dtype=float)),
                    errors="coerce",
                ).sum()
                + pd.to_numeric(
                    operator_energy.get("secondary_energy_consumption", pd.Series(dtype=float)),
                    errors="coerce",
                ).sum()
            ) / KWH_PER_TWH

        solara.Markdown(
            "\n".join(
                [
                    f"### {effective_operator} Drill-Down",
                    f"- Source: `{source_label}`",
                    f"- Latest year: `{latest_year or 'n/a'}`",
                    f"- Latest fleet stock: `{latest_assets}`",
                    f"- Latest alternative share: `{latest_alternative_share:.2%}`",
                    f"- Total investment in view: `{total_investment:,.0f} EUR`",
                    f"- Total energy in view: `{total_energy_twh:,.4f} TWh`",
                ],
            ),
        )

        if not operator_agents.empty:
            ordered = operator_agents.sort_values("year")
            fig = Figure(figsize=(9.2, 4.8))
            ax = fig.subplots()
            ax.plot(
                ordered["year"].astype(int),
                ordered["alternative_share"].astype(float),
                marker="o",
                color="#2a6f97",
                label="Alternative share",
            )
            ax.set_ylim(0.0, 1.0)
            ax.set_ylabel("Alternative share")
            ax.set_xlabel("Year")
            ax.grid(alpha=0.25)
            ax2 = ax.twinx()
            ax2.plot(
                ordered["year"].astype(int),
                ordered["total_assets"].astype(float),
                marker="s",
                color="#386641",
                label="Fleet stock",
            )
            ax2.set_ylabel("Fleet stock")
            ax.set_title(f"{effective_operator}: Adoption and Fleet Stock")
            _show_figure(fig)

        if latest_year is not None and not operator_technology.empty:
            latest_tech = operator_technology.loc[
                pd.to_numeric(operator_technology["year"], errors="coerce").eq(latest_year)
            ]
            if not latest_tech.empty and stock_count_column in latest_tech.columns:
                table = (
                    latest_tech.groupby("current_technology", as_index=False)[stock_count_column]
                    .sum()
                    .sort_values(stock_count_column, ascending=False)
                )
                solara.Markdown("#### Latest Technology Mix")
                _show_dataframe(table, max_rows=8)

        if latest_year is not None and not operator_energy.empty:
            solara.Markdown("#### Latest Energy by Carrier")
            _show_dataframe(_energy_by_carrier_table(operator_energy, latest_year), max_rows=8)

        if latest_year is not None and not operator_investments.empty:
            latest_investments = operator_investments.loc[
                pd.to_numeric(operator_investments["year"], errors="coerce").eq(latest_year)
            ]
            if not latest_investments.empty:
                columns = [
                    column
                    for column in (
                        "year",
                        "operator_name",
                        "investment_cost_eur",
                        "technology_name",
                        "current_technology",
                    )
                    if column in latest_investments.columns
                ]
                solara.Markdown("#### Latest Investment Rows")
                _show_dataframe(latest_investments[columns], max_rows=8)

    @solara.component
    def OperatorDrilldown(model: NATMModel):
        update_counter.get()
        with solara.Card("Operator Drill-Down", style={"margin-bottom": "28px"}):
            OperatorDrilldownContent(_live_result_frames(model), "live case")

    @solara.component
    def SavedOperatorDrilldown(folder_name: str):
        with solara.Card("Operator Drill-Down", style={"margin-bottom": "28px"}):
            OperatorDrilldownContent(_load_result_frames(folder_name), f"saved: {folder_name}")

    @solara.component
    def ReportTablesContent(frames: dict[str, pd.DataFrame], source_label: str):
        agent_frame = frames.get("agents", pd.DataFrame())
        technology_frame = frames.get("technology", pd.DataFrame())
        energy_frame = frames.get("energy", pd.DataFrame())
        investment_frame = frames.get("investments", pd.DataFrame())
        robust_frontier = frames.get("robust_frontier", pd.DataFrame())
        latest_year = (
            _latest_year(agent_frame)
            or _latest_year(technology_frame)
            or _latest_year(energy_frame)
            or _latest_year(investment_frame)
            or _latest_year(robust_frontier)
        )
        solara.Markdown(f"### Report Tables ({source_label})")
        solara.Markdown("Compact tables for checking values and preparing report screenshots.")
        if latest_year is None:
            solara.Markdown("No year-indexed data is available.")
            return

        if not agent_frame.empty:
            latest_agents = agent_frame.loc[
                pd.to_numeric(agent_frame["year"], errors="coerce").eq(latest_year)
            ]
            columns = [
                column
                for column in (
                    "year",
                    "operator_name",
                    "operator_country",
                    "total_assets",
                    "alternative_assets",
                    "alternative_share",
                )
                if column in latest_agents.columns
            ]
            solara.Markdown("#### Final Operator Stock")
            _show_dataframe(
                latest_agents[columns].sort_values("operator_name"),
                max_rows=16,
            )

        if not technology_frame.empty:
            latest_technology = technology_frame.loc[
                pd.to_numeric(technology_frame["year"], errors="coerce").eq(latest_year)
            ]
            if stock_count_column in latest_technology.columns:
                technology_table = (
                    latest_technology.groupby("current_technology", as_index=False)[
                        stock_count_column
                    ]
                    .sum()
                    .sort_values(stock_count_column, ascending=False)
                )
                solara.Markdown("#### Final Technology Mix")
                _show_dataframe(technology_table, max_rows=16)

        if not energy_frame.empty:
            solara.Markdown("#### Final Energy by Carrier")
            _show_dataframe(_energy_by_carrier_table(energy_frame, latest_year), max_rows=16)

        if not investment_frame.empty and "investment_cost_eur" in investment_frame.columns:
            investment_table = (
                investment_frame.groupby("operator_name", as_index=False)["investment_cost_eur"]
                .sum()
                .sort_values("investment_cost_eur", ascending=False)
            )
            solara.Markdown("#### Total Investments by Operator")
            _show_dataframe(investment_table, max_rows=16)

        if not robust_frontier.empty and "robust_score" in robust_frontier.columns:
            robust_latest = robust_frontier.loc[
                pd.to_numeric(robust_frontier["year"], errors="coerce").eq(latest_year)
            ].copy()
            robust_latest = robust_latest.drop_duplicates(
                subset=[
                    column
                    for column in (
                        "operator_name",
                        "asset_id",
                        "segment",
                        "candidate_technology",
                    )
                    if column in robust_latest.columns
                ],
            )
            robust_columns = [
                column
                for column in (
                    "operator_name",
                    "segment",
                    "decision_attitude",
                    "candidate_technology",
                    "expected_utility",
                    "robust_score",
                    "selected_flag",
                )
                if column in robust_latest.columns
            ]
            if robust_columns:
                solara.Markdown("#### Robust Frontier")
                _show_dataframe(robust_latest[robust_columns], max_rows=16)

    @solara.component
    def ReportTables(model: NATMModel):
        update_counter.get()
        with solara.Card("Report Tables", style={"margin-bottom": "28px"}):
            ReportTablesContent(_live_result_frames(model), "live case")

    @solara.component
    def SavedReportTables(folder_name: str):
        with solara.Card("Report Tables", style={"margin-bottom": "28px"}):
            ReportTablesContent(_load_result_frames(folder_name), f"saved: {folder_name}")

    @solara.component
    def AviationPreprocessingExplorer(_model: NATMModel | None = None):
        if sector_name != "aviation":
            return
        frames = _load_aviation_preprocessing_frames()
        if not frames or all(frame.empty for frame in frames.values()):
            with solara.Card("Aviation Preprocessing Explorer"):
                solara.Markdown(
                    "No aviation preprocessing outputs were found in `data/processed/aviation`.",
                )
            return

        enriched_stock = frames.get("enriched_stock", pd.DataFrame())
        openap_flights = frames.get("openap_flights", pd.DataFrame())
        route_summary = frames.get("openap_route_summary", pd.DataFrame())
        activity_profiles = frames.get("activity_profiles", pd.DataFrame())

        with solara.Card("Aviation Preprocessing Explorer", style={"margin-bottom": "28px"}):
            solara.Markdown("### Processed Data Snapshot")
            solara.Markdown(
                "\n".join(
                    [
                        f"- Enriched stock rows: `{len(enriched_stock)}`",
                        f"- OpenAP flight rows: `{len(openap_flights)}`",
                        f"- OpenAP route rows: `{len(route_summary)}`",
                        f"- Activity profile rows: `{len(activity_profiles)}`",
                        f"- Folder: `{PROCESSED_AVIATION_ROOT}`",
                    ],
                ),
            )

            if not openap_flights.empty:
                processed = openap_flights.loc[
                    pd.to_numeric(openap_flights.get("fuel_kg"), errors="coerce") > 0.0
                ]
                total_fuel = pd.to_numeric(processed.get("fuel_kg"), errors="coerce").sum()
                total_energy = pd.to_numeric(processed.get("energy_mwh"), errors="coerce").sum()
                solara.Markdown(
                    "\n".join(
                        [
                            "### OpenAP Baseline Totals",
                            f"- Flights with estimated fuel: `{len(processed)}`",
                            f"- Fuel: `{total_fuel:,.1f} kg`",
                            f"- Energy: `{total_energy:,.4f} MWh`",
                        ],
                    ),
                )
                emission_columns = _emission_columns(processed)
                if emission_columns:
                    solara.Markdown("#### OpenAP Pollutants")
                    _show_dataframe(
                        _emission_totals_table(processed, emission_columns),
                        max_rows=len(emission_columns),
                    )

            mapping_log = frames.get("openap_mapping_log", pd.DataFrame())
            if not mapping_log.empty:
                solara.Markdown("#### Aircraft Type Mapping Log")
                _show_dataframe(mapping_log, max_rows=12)

            type_summary = frames.get("openap_type_summary", pd.DataFrame())
            if not type_summary.empty:
                solara.Markdown("#### OpenAP Aircraft Type Summary")
                _show_dataframe(type_summary, max_rows=12)

            matching_report = frames.get("matching_report", pd.DataFrame())
            if not matching_report.empty:
                solara.Markdown("#### Stock Matching Report")
                _show_dataframe(matching_report, max_rows=12)

            airport_allocation = frames.get("airport_allocation", pd.DataFrame())
            if not airport_allocation.empty:
                solara.Markdown("#### Airport Allocation")
                _show_dataframe(airport_allocation, max_rows=12)

    @solara.component
    def FlightRouteNetwork(_model: NATMModel | None = None):
        if sector_name != "aviation":
            return
        route_summary = _load_aviation_preprocessing_frames().get(
            "openap_route_summary",
            pd.DataFrame(),
        )
        with solara.Card("Flight Route Network", style={"margin-bottom": "28px"}):
            if route_summary.empty:
                solara.Markdown(
                    "No OpenAP route summary was found. Run aviation preprocessing with "
                    "`openap.estimate_fuel: true` first.",
                )
                return
            metric_options = [
                column
                for column in (
                    "number_of_trips",
                    "total_fuel_kg",
                    "total_energy_mwh",
                    "total_co2_kg",
                )
                if column in route_summary.columns
            ]
            metric, set_metric = solara.use_state(
                metric_options[0] if metric_options else "number_of_trips",
            )
            top_n_default = min(12, max(len(route_summary), 1))
            top_n, set_top_n = solara.use_state(top_n_default)
            if not metric_options:
                solara.Markdown("Route summary has no plottable metric columns.")
                return

            effective_metric = metric if metric in metric_options else metric_options[0]
            solara.Select(
                "Edge weight",
                values=metric_options,
                value=effective_metric,
                on_value=set_metric,
            )
            solara.SliderInt(
                "Top routes",
                value=min(top_n, len(route_summary)),
                min=1,
                max=max(len(route_summary), 1),
                step=1,
                on_value=set_top_n,
            )

            routes = route_summary.copy()
            routes[effective_metric] = pd.to_numeric(routes[effective_metric], errors="coerce")
            routes = routes.dropna(subset=[effective_metric])
            routes = routes.loc[routes[effective_metric] > 0.0]
            routes = routes.sort_values(effective_metric, ascending=False).head(top_n)
            if routes.empty:
                solara.Markdown("No positive route weights are available.")
                return

            graph = nx.DiGraph()
            for row in routes.itertuples(index=False):
                origin = str(getattr(row, "origin", "")).strip()
                destination = str(getattr(row, "destination", "")).strip()
                weight = float(getattr(row, effective_metric))
                if origin and destination:
                    graph.add_edge(origin, destination, weight=weight)

            fig = Figure(figsize=(9.4, 6.4))
            ax = fig.subplots()
            positions = nx.spring_layout(graph, seed=42, k=1.6)
            weights = [graph[u][v]["weight"] for u, v in graph.edges()]
            max_weight = max(weights) if weights else 1.0
            widths = [1.0 + 5.0 * weight / max_weight for weight in weights]
            node_sizes = [900 + 280 * graph.degree(node) for node in graph.nodes()]
            nx.draw_networkx_nodes(
                graph,
                positions,
                node_size=node_sizes,
                node_color="#2a6f97",
                alpha=0.9,
                ax=ax,
            )
            nx.draw_networkx_edges(
                graph,
                positions,
                width=widths,
                edge_color="#9c6644",
                arrows=True,
                arrowsize=18,
                alpha=0.7,
                ax=ax,
            )
            nx.draw_networkx_labels(
                graph,
                positions,
                font_size=10,
                font_color="white",
                ax=ax,
            )
            ax.set_title(f"Top Flight Routes by {effective_metric}")
            ax.axis("off")
            _show_figure(fig)

            solara.Markdown("#### Route Table")
            columns = [
                column
                for column in (
                    "origin",
                    "destination",
                    "route",
                    "raw_aircraft_type",
                    "openap_type",
                    "year",
                    effective_metric,
                )
                if column in routes.columns
            ]
            _show_dataframe(routes[columns], max_rows=top_n)

    @solara.component
    def FlightFuelDemandMap(_model: NATMModel | None = None, result_folder: str | None = None):
        if sector_name != "aviation":
            return
        frames = _load_aviation_preprocessing_frames()
        airport_metadata = frames.get("airport_metadata", pd.DataFrame())
        saved_frames = _load_result_frames(result_folder) if result_folder else {}
        allocated_airports = _normalize_airport_fuel_demand(
            saved_frames.get("airport_fuel_demand", pd.DataFrame()),
            airport_metadata,
        )
        allocated_routes = _normalize_route_energy_flow(
            saved_frames.get("route_energy_flow", pd.DataFrame()),
            airport_metadata,
        )
        uses_allocated_outputs = not allocated_routes.empty
        route_summary = (
            allocated_routes
            if uses_allocated_outputs
            else frames.get("openap_route_summary", pd.DataFrame())
        )
        with solara.Card("Airport Fuel Demand Map", style={"margin-bottom": "28px"}):
            if route_summary.empty:
                solara.Markdown(
                    "No route fuel data was found. Run aviation preprocessing with "
                    "`openap.estimate_fuel: true`, or generate postprocessed airport fuel "
                    "allocation outputs for the selected results folder.",
                )
                return
            if airport_metadata.empty and not uses_allocated_outputs:
                solara.Markdown(
                    "No airport coordinate metadata was found, so the map cannot be drawn.",
                )
                return

            metric_options = [
                column
                for column in (
                    (
                        "fuel_uplift_mwh",
                        "fuel_demand",
                        "energy_demand",
                        "fuel_uplift_kg",
                        "co2",
                        "trips",
                    )
                    if uses_allocated_outputs
                    else (
                        "total_fuel_kg",
                        "total_energy_mwh",
                        "total_co2_kg",
                        "number_of_trips",
                    )
                )
                if column in route_summary.columns
            ]
            if not metric_options:
                solara.Markdown("Route summary has no map metric columns.")
                return

            selected_metric, set_selected_metric = solara.use_state(metric_options[0])
            basis_options = ["Departures only", "Origin + destination activity"]
            selected_basis, set_selected_basis = solara.use_state(basis_options[0])
            available_years = (
                sorted(route_summary["year"].dropna().astype(int).unique().tolist())
                if "year" in route_summary.columns
                else []
            )
            selected_year, set_selected_year = solara.use_state(
                available_years[-1] if available_years else None,
            )

            effective_metric = (
                selected_metric if selected_metric in metric_options else metric_options[0]
            )
            effective_basis = (
                selected_basis if selected_basis in basis_options else basis_options[0]
            )
            effective_year = (
                (selected_year if selected_year in available_years else available_years[-1])
                if available_years
                else None
            )

            solara.Markdown(
                "Airport bubbles show demand associated with airports; route lines are drawn "
                "on a lightweight Europe basemap using airport coordinates.",
            )
            if uses_allocated_outputs:
                solara.Markdown(
                    "Using postprocessed airport fuel allocation outputs from "
                    f"`simulation_results/{result_folder}`.",
                )
            solara.Select(
                "Map metric",
                values=metric_options,
                value=effective_metric,
                on_value=set_selected_metric,
            )
            if available_years:
                solara.SliderInt(
                    "Map year",
                    value=effective_year,
                    min=available_years[0],
                    max=available_years[-1],
                    step=1,
                    on_value=set_selected_year,
                )
            if not uses_allocated_outputs:
                solara.ToggleButtonsSingle(
                    value=effective_basis,
                    values=basis_options,
                    on_value=set_selected_basis,
                )

            routes = route_summary.copy()
            if effective_year is not None and "year" in routes.columns:
                routes = routes.loc[routes["year"].astype(int).eq(effective_year)].copy()
            routes[effective_metric] = pd.to_numeric(routes[effective_metric], errors="coerce")
            routes = routes.dropna(subset=[effective_metric])
            routes = routes.loc[routes[effective_metric] > 0.0]
            if routes.empty:
                solara.Markdown("No positive route weights are available.")
                return

            top_n_default = min(20, max(len(routes), 1))
            top_n, set_top_n = solara.use_state(top_n_default)
            effective_top_n = min(top_n, len(routes))
            solara.SliderInt(
                "Top routes on map",
                value=effective_top_n,
                min=1,
                max=max(len(routes), 1),
                step=1,
                on_value=set_top_n,
            )
            routes = routes.sort_values(effective_metric, ascending=False).head(effective_top_n)

            if not uses_allocated_outputs:
                airport_lookup = airport_metadata.set_index("airport_code")
                routes = routes.merge(
                    airport_lookup[["latitude", "longitude"]].add_prefix("origin_"),
                    left_on="origin",
                    right_index=True,
                    how="left",
                )
                routes = routes.merge(
                    airport_lookup[["latitude", "longitude"]].add_prefix("destination_"),
                    left_on="destination",
                    right_index=True,
                    how="left",
                )
                routes = routes.dropna(
                    subset=[
                        "origin_latitude",
                        "origin_longitude",
                        "destination_latitude",
                        "destination_longitude",
                    ],
                )
            if routes.empty:
                solara.Markdown(
                    "Routes exist, but their airports were not found in the coordinate metadata.",
                )
                return

            if uses_allocated_outputs and not allocated_airports.empty:
                airport_metric = (
                    effective_metric
                    if effective_metric in allocated_airports.columns
                    else (
                        "fuel_demand"
                        if "fuel_demand" in allocated_airports.columns
                        else "energy_demand"
                    )
                )
                airport_demand = allocated_airports.copy()
                if effective_year is not None and "year" in airport_demand.columns:
                    airport_demand = airport_demand.loc[
                        airport_demand["year"].astype(int).eq(effective_year)
                    ].copy()
                airport_demand[airport_metric] = pd.to_numeric(
                    airport_demand[airport_metric],
                    errors="coerce",
                )
                airport_demand = airport_demand.dropna(subset=[airport_metric])
                group_columns = [
                    column
                    for column in (
                        "airport_code",
                        "airport_name",
                        "country",
                        "latitude",
                        "longitude",
                    )
                    if column in airport_demand.columns
                ]
                airport_demand = (
                    airport_demand.groupby(group_columns, dropna=False, as_index=False)[
                        airport_metric
                    ]
                    .sum()
                    .rename(columns={airport_metric: "airport_metric"})
                )
            else:
                origin_demand = routes[["origin", effective_metric]].rename(
                    columns={"origin": "airport_code", effective_metric: "airport_metric"},
                )
                if effective_basis == "Origin + destination activity":
                    destination_demand = routes[["destination", effective_metric]].rename(
                        columns={
                            "destination": "airport_code",
                            effective_metric: "airport_metric",
                        },
                    )
                    airport_demand = pd.concat(
                        [origin_demand, destination_demand],
                        ignore_index=True,
                    )
                else:
                    airport_demand = origin_demand
                airport_demand = (
                    airport_demand.groupby("airport_code", as_index=False)["airport_metric"]
                    .sum()
                    .merge(airport_metadata, on="airport_code", how="left")
                    .dropna(subset=["latitude", "longitude"])
                )

            if airport_demand.empty:
                solara.Markdown("No airport demand rows are available for this map selection.")
                return

            max_airport_metric = max(float(airport_demand["airport_metric"].max()), 1.0)
            max_route_metric = float(routes[effective_metric].max())
            fig = Figure(figsize=(10.2, 6.8))
            ax = fig.subplots()
            _draw_europe_basemap(ax)
            for row in routes.itertuples(index=False):
                weight = float(getattr(row, effective_metric))
                width = 0.8 + 5.2 * weight / max_route_metric
                ax.plot(
                    [row.origin_longitude, row.destination_longitude],
                    [row.origin_latitude, row.destination_latitude],
                    color="#8d5524",
                    linewidth=width,
                    alpha=0.42,
                    zorder=1,
                )
                mid_lon = (row.origin_longitude + row.destination_longitude) / 2
                mid_lat = (row.origin_latitude + row.destination_latitude) / 2
                ax.annotate(
                    "",
                    xy=(row.destination_longitude, row.destination_latitude),
                    xytext=(mid_lon, mid_lat),
                    arrowprops={
                        "arrowstyle": "->",
                        "color": "#8d5524",
                        "alpha": 0.5,
                        "lw": max(width * 0.45, 0.8),
                    },
                    zorder=2,
                )

            sizes = 280 + 1500 * airport_demand["airport_metric"] / max_airport_metric
            scatter = ax.scatter(
                airport_demand["longitude"],
                airport_demand["latitude"],
                s=sizes,
                c=airport_demand["airport_metric"],
                cmap="YlOrRd",
                edgecolor="#1f2933",
                linewidth=1.0,
                alpha=0.88,
                zorder=3,
            )
            for row in airport_demand.itertuples(index=False):
                ax.text(
                    row.longitude,
                    row.latitude + 0.22,
                    row.airport_code,
                    ha="center",
                    va="bottom",
                    fontsize=10,
                    fontweight="bold",
                    color="#1f2933",
                    zorder=4,
                )

            lon_values = pd.concat([routes["origin_longitude"], routes["destination_longitude"]])
            lat_values = pd.concat([routes["origin_latitude"], routes["destination_latitude"]])
            lon_margin = max((lon_values.max() - lon_values.min()) * 0.12, 2.0)
            lat_margin = max((lat_values.max() - lat_values.min()) * 0.18, 2.0)
            ax.set_xlim(
                min(-12.0, lon_values.min() - lon_margin),
                max(32.0, lon_values.max() + lon_margin),
            )
            ax.set_ylim(
                min(35.0, lat_values.min() - lat_margin),
                max(62.0, lat_values.max() + lat_margin),
            )
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title(f"Europe Airport Demand and Flight Routes by {effective_metric}")
            ax.grid(color="white", linewidth=0.8, alpha=0.55)
            ax.set_aspect("equal", adjustable="box")
            colorbar = fig.colorbar(scatter, ax=ax, fraction=0.036, pad=0.02)
            colorbar.set_label(effective_metric)
            _show_figure(fig)

            solara.Markdown("#### Airport Demand Table")
            table_columns = [
                column
                for column in (
                    "airport_code",
                    "airport_name",
                    "country",
                    "carrier",
                    "allocation_method",
                    "airport_metric",
                )
                if column in airport_demand.columns
            ]
            table = airport_demand[table_columns].sort_values("airport_metric", ascending=False)
            _show_dataframe(table, max_rows=16)

    @solara.component
    def SavedResultsView(folder_name: str):
        with solara.Column():
            SavedLatestSummary(folder_name)
            SavedOperatorShares(folder_name)
            SavedTechnologyMix(folder_name)
            SavedEnergyByCarrier(folder_name)
            SavedEmissionsOverview(folder_name)
            SavedInvestmentsByOperator(folder_name)
            SavedRobustFrontier(folder_name)
            SavedOperatorDrilldown(folder_name)
            SavedReportTables(folder_name)
            if sector_name == "aviation":
                AviationPreprocessingExplorer()
                FlightRouteNetwork()
                FlightFuelDemandMap(result_folder=folder_name)

    model_params = {
        "scenario": scenario,
        "seed": {
            "type": "SliderInt",
            "value": 42,
            "label": "Random seed",
            "min": 1,
            "max": 100,
            "step": 1,
        },
    }

    live_components = [
        LatestSummary,
        make_plot_component(f"{sector_name}_alternative_share"),
        make_plot_component(f"{sector_name}_transition_pressure"),
        make_plot_component(f"{sector_name}_policy_support"),
        OperatorShares,
        TechnologyMix,
        EnergyByCarrier,
        EmissionsOverview,
        InvestmentsByOperator,
        RobustFrontier,
        OperatorDrilldown,
        ReportTables,
    ]
    if sector_name == "aviation":
        live_components.extend(
            [
                AviationPreprocessingExplorer,
                FlightRouteNetwork,
                FlightFuelDemandMap,
            ],
        )

    model = _build_model(scenario=scenario, seed=42)
    live_dashboard = SolaraViz(
        model,
        components=live_components,
        model_params=model_params,
        name=title,
    )

    @solara.component
    def Page():
        result_options = _available_result_folders()
        mode, set_mode = solara.use_state("Live case")
        selected_result, set_selected_result = solara.use_state(
            result_options[0] if result_options else None,
        )

        with solara.Column():
            with solara.Card("Dashboard Source", style={"margin-bottom": "20px"}):
                solara.Markdown("### Data Source")
                solara.ToggleButtonsSingle(
                    value=mode,
                    values=["Live case", "Saved results"],
                    on_value=set_mode,
                )
                if mode == "Saved results":
                    if result_options:
                        effective_result = (
                            selected_result
                            if selected_result in result_options
                            else result_options[0]
                        )
                        solara.Select(
                            "Results folder",
                            values=result_options,
                            value=effective_result,
                            on_value=set_selected_result,
                        )
                    else:
                        solara.Markdown(
                            "No compatible folders were found in `simulation_results/`.",
                        )

            if mode == "Live case":
                solara.display(live_dashboard)
            elif result_options:
                effective_result = (
                    selected_result if selected_result in result_options else result_options[0]
                )
                SavedResultsView(effective_result)
            else:
                solara.Markdown("No compatible saved results are available yet.")

    return Page


_DASHBOARD_PAGE_CACHE = {}


def _dashboard_page_for_case(case_name: str):
    if case_name not in _DASHBOARD_PAGE_CACHE:
        _DASHBOARD_PAGE_CACHE[case_name] = build_case_dashboard(case_name=case_name)
    return _DASHBOARD_PAGE_CACHE[case_name]


@solara.component
def Page():
    case_options = _available_live_case_names()
    selected_case, set_selected_case = solara.use_state(case_options[0] if case_options else "")
    if not case_options:
        solara.Warning("No dashboard-compatible case folders found under `data/`.")
        return

    effective_case = selected_case if selected_case in case_options else case_options[0]

    with solara.Column():
        with solara.Card("Case", style={"margin-bottom": "20px"}):
            solara.Select(
                "Live case",
                values=case_options,
                value=effective_case,
                on_value=set_selected_case,
            )

        case_page = _dashboard_page_for_case(effective_case)
        case_page()


if __name__ == "__main__":
    print("Run this dashboard with: solara run dashboard_examples/common_case_dashboard.py")
