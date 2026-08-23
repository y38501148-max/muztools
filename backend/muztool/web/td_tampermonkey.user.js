// ==UserScript==
// @name         MuzTool 电脑端 TD 桥接助手
// @namespace    https://muztool.local/
// @version      1.1.0
// @description  当浏览器限制 WebUI 访问本机服务时，将 TD 请求转交给 127.0.0.1 本地桥接脚本。
// @match        http://150.138.79.9:10023/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-start
// ==/UserScript==

(() => {
  "use strict";

  function reply(requestId, payload) {
    window.postMessage({
      source: "muztool-tampermonkey",
      type: "td-response",
      requestId,
      payload
    }, "*");
  }

  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (event.source !== window || data.source !== "muztool-web" || data.type !== "td-request") return;

    const path = data.path === "/health" ? "/health" : "/td/manual";
    const method = data.method === "GET" ? "GET" : "POST";
    GM_xmlhttpRequest({
      method,
      url: `http://127.0.0.1:18788${path}`,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-MuzTool-Bridge-Token": String(data.token || "")
      },
      data: method === "GET" ? undefined : JSON.stringify(data.payload || {}),
      timeout: method === "GET" ? 8000 : 65000,
      onload: (response) => {
        let payload;
        try { payload = JSON.parse(response.responseText || "{}"); }
        catch { payload = { success: false, message: "本地桥接返回了无效数据" }; }
        if (response.status < 200 || response.status >= 300) {
          payload.success = false;
          payload.message = payload.message || `本地桥接请求失败 (${response.status})`;
        }
        reply(data.requestId, payload);
      },
      ontimeout: () => reply(data.requestId, { success: false, message: "连接本地桥接超时" }),
      onerror: () => reply(data.requestId, { success: false, message: "无法连接本地桥接，请确认脚本正在运行" })
    });
  });
})();
