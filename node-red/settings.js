// node-red/settings.js
// av_unified_mvp 专用 Node-RED 配置
// 关键作用：
//   1. flowFile 指向项目内 flows.json（与仓库同步）
//   2. httpAdminMiddleware 移除 X-Frame-Options + 放开 frame-ancestors，
//      允许 dashboard.html 的"编程"tab 用 <iframe> 嵌入 Node-RED 编辑器
//   3. 关闭弹出"项目"向导（首次启动会问用户是否启用 projects feature）
//
// 启动方式：
//   node-red --userDir ./node-red --port 1880

module.exports = {
    flowFile: "flows.json",
    flowFilePretty: true,
    uiPort: process.env.PORT || 1880,
    uiHost: "0.0.0.0",
    credentialSecret: "av_unified_mvp_dev",

    // 禁掉 Node-RED 内部 helmet 加的 X-Frame-Options，
    // 改用 frame-ancestors *，让 dashboard 同/异端口都能 iframe
    httpAdminMiddleware: function (req, res, next) {
        res.removeHeader("X-Frame-Options");
        res.setHeader("Content-Security-Policy", "frame-ancestors *");
        next();
    },

    logging: {
        console: {
            level: "info",
            metrics: false,
            audit: false,
        },
    },

    // 不启用 projects feature（避免首启弹向导）
    editorTheme: {
        projects: { enabled: false },
        page: { title: "Node-RED · av_unified_mvp" },
        header: { title: "Node-RED · av_unified_mvp" },
    },

    functionGlobalContext: {},
    exportGlobalContextKeys: false,
};
