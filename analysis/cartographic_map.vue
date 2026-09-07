<template>
  <iframe ref="frame" :srcdoc="shell_html" title="NATM cartographic map" style="width:100%;height:720px;border:0"></iframe>
</template>
<script>
module.exports = {
  data() {
    return { loaded: false };
  },
  mounted() {
    this.$refs.frame.addEventListener("load", () => {
      this.loaded = true;
      this.send();
    });
  },
  watch: {
    shell_html() {
      // A new document is about to load into the (still-mounted) iframe;
      // wait for its own 'load' event before posting data again.
      this.loaded = false;
    },
    map_data() {
      this.send();
    },
  },
  methods: {
    send() {
      if (this.loaded && this.$refs.frame && this.$refs.frame.contentWindow) {
        // this.map_data is a Vue-reactive proxy over the widget trait value,
        // which the structured clone algorithm behind postMessage refuses to
        // clone directly ("could not be cloned"). Round-tripping through
        // JSON strips the proxy down to a plain, cloneable object.
        this.$refs.frame.contentWindow.postMessage(JSON.parse(JSON.stringify(this.map_data)), "*");
      }
    },
  },
};
</script>
