from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pandas as pd

try:
    import solara
    from matplotlib.figure import Figure
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
RESULTS_ROOT = Path(__file__).resolve().parents[1] / "simulation_results"


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


@solara.component
def _ChartContainer(title: str, content_component):
    with solara.Card(title, style={"padding-bottom": "40px", "margin-bottom": "56px"}):
        content_component()
        solara.HTML(tag="div", unsafe_innerHTML="", style={"height": "40px"})


def _build_model(*, scenario: NATMScenario, seed: int = 42) -> NATMModel:
    return NATMModel(scenario=scenario, seed=seed)


def build_case_dashboard(
    *,
    case_name: str,
    title: str,
    sector_name: str,
    application_name: str,
    technology_frame_getter,
    energy_frame_getter,
    investment_frame_getter,
    stock_count_column: str,
    stock_axis_label: str,
):
    scenario_path = resolve_case_config(case_name)
    scenario = NATMScenario.from_yaml(scenario_path)
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
    def SavedResultsView(folder_name: str):
        with solara.Column():
            SavedLatestSummary(folder_name)
            SavedOperatorShares(folder_name)
            SavedTechnologyMix(folder_name)
            SavedEnergyByCarrier(folder_name)
            SavedInvestmentsByOperator(folder_name)

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

    model = _build_model(scenario=scenario, seed=42)
    live_dashboard = SolaraViz(
        model,
        components=[
            LatestSummary,
            make_plot_component(f"{sector_name}_alternative_share"),
            make_plot_component(f"{sector_name}_transition_pressure"),
            make_plot_component(f"{sector_name}_policy_support"),
            OperatorShares,
            TechnologyMix,
            EnergyByCarrier,
            InvestmentsByOperator,
        ],
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

    return Page()
