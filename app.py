import os
import json
from datetime import datetime
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, Response
import uvicorn
from uptime_kuma_api import UptimeKumaApi

app = FastAPI(title="Uptime Kuma Backup Manager")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Uptime Kuma Backup Tool</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #12151a; color: #f0f3f6; margin: 0; padding: 40px 20px; }
        .container { max-width: 580px; margin: 0 auto; background: #1c2128; border: 1px solid #30363d; border-radius: 8px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        h2 { margin-top: 0; color: #58a6ff; font-size: 1.4rem; border-bottom: 1px solid #30363d; padding-bottom: 12px; }
        label { display: block; font-size: 0.85rem; color: #8b949e; margin-bottom: 6px; margin-top: 14px; }
        input[type="text"], input[type="password"], input[type="file"] { width: 100%; box-sizing: border-box; background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px; border-radius: 6px; font-size: 0.95rem; }
        .btn { display: inline-block; width: 100%; border: none; padding: 10px; border-radius: 6px; font-weight: 600; font-size: 0.95rem; cursor: pointer; margin-top: 18px; transition: 0.2s; }
        .btn-export { background: #238636; color: #fff; }
        .btn-export:hover { background: #2ea043; }
        .btn-import { background: #1f6feb; color: #fff; }
        .btn-import:hover { background: #388bfd; }
        .section { margin-top: 28px; padding-top: 20px; border-top: 1px solid #30363d; }
        .msg { padding: 12px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9rem; }
        .msg-success { background: #1f3b2c; border: 1px solid #238636; color: #7ee787; }
        .msg-error { background: #3e1b1e; border: 1px solid #da3633; color: #f85149; }
    </style>
</head>
<body>
<div class="container">
    <h2>Uptime Kuma Backup & Restore</h2>
    __STATUS_MSG__
    
    <!-- Форма создания бэкапа -->
    <form action="/export" method="post">
        <label>URL Uptime Kuma:</label>
        <input type="text" name="url" value="__DEFAULT_URL__" required>
        <label>Логин:</label>
        <input type="text" name="username" value="admin" required>
        <label>Пароль:</label>
        <input type="password" name="password" required>
        <button type="submit" class="btn btn-export">⬇ Скачать Backup (.json)</button>
    </form>

    <!-- Форма восстановления -->
    <div class="section">
        <h3>Восстановление из JSON</h3>
        <form action="/import" method="post" enctype="multipart/form-data">
            <label>URL Uptime Kuma:</label>
            <input type="text" name="url" value="__DEFAULT_URL__" required>
            <label>Логин:</label>
            <input type="text" name="username" value="admin" required>
            <label>Пароль:</label>
            <input type="password" name="password" required>
            <label>Файл резервной копии:</label>
            <input type="file" name="backup_file" accept=".json" required>
            <button type="submit" class="btn btn-import">⬆ Загрузить и восстановить</button>
        </form>
    </div>
</div>
</body>
</html>
"""

def render_page(status: str = "", is_error: bool = False, url: str = "http://localhost:3001"):
    msg = ""
    if status:
        css_class = "msg-error" if is_error else "msg-success"
        msg = f'<div class="msg {css_class}">{status}</div>'
    
    html = HTML_TEMPLATE.replace("__STATUS_MSG__", msg).replace("__DEFAULT_URL__", url)
    return HTMLResponse(html)

@app.get("/", response_class=HTMLResponse)
async def index():
    default_kuma = os.getenv("KUMA_URL", "http://host.docker.internal:3001")
    return render_page(url=default_kuma)

@app.post("/export")
async def export_data(url: str = Form(...), username: str = Form(...), password: str = Form(...)):
    try:
        api = UptimeKumaApi(url)
        api.login(username, password)
        monitors = api.get_monitors()
        notifications = api.get_notifications()
        api.disconnect()

        payload = {
            "exported_at": datetime.now().isoformat(),
            "monitorList": monitors,
            "notificationList": notifications
        }
        filename = f"kuma_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return render_page(status=f"Ошибка экспорта: {str(e)}", is_error=True, url=url)

@app.post("/import")
async def import_data(
    url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    backup_file: UploadFile = File(...)
):
    try:
        content = await backup_file.read()
        data = json.loads(content.decode("utf-8"))

        monitors = data.get("monitorList", [])
        if not monitors and isinstance(data, list):
            monitors = data

        api = UptimeKumaApi(url)
        api.login(username, password)

        success, errs = 0, 0
        for m in monitors:
            name = m.get("name")
            params = {
                "type": m.get("type", "http"),
                "name": name,
                "interval": m.get("interval", 60),
                "retry_interval": m.get("retryInterval", m.get("retry_interval", 60)),
                "max_retries": m.get("maxretries", m.get("max_retries", 0)),
            }
            if m.get("url"):
                params["url"] = m["url"]
            if m.get("hostname"):
                params["hostname"] = m["hostname"]
            if m.get("port"):
                params["port"] = int(m["port"])

            try:
                api.add_monitor(**params)
                success += 1
            except Exception:
                errs += 1

        api.disconnect()
        return render_page(status=f"Импорт завершен! Добавлено: {success}, ошибок/пропусков: {errs}", is_error=False, url=url)
    except Exception as e:
        return render_page(status=f"Ошибка импорта: {str(e)}", is_error=True, url=url)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
