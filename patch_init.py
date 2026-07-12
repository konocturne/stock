import re

with open("dashboard/app.js", "r") as f:
    app_js = f.read()

app_js = app_js.replace("document.getElementById('loading').style.display      = 'none';", "const loadEl = document.getElementById('loading'); if(loadEl) loadEl.style.display = 'none';")
app_js = app_js.replace("document.getElementById('main-content').style.display = '';", "const mainEl = document.getElementById('main-content'); if(mainEl) mainEl.style.display = '';")
app_js = app_js.replace("document.getElementById('error-screen').style.display = '';", "const errEl = document.getElementById('error-screen'); if(errEl) errEl.style.display = '';")
app_js = app_js.replace("document.getElementById('updated-at').textContent =", "const updEl = document.getElementById('updated-at'); if(updEl) updEl.textContent =")
app_js = app_js.replace("document.getElementById('perf-date').textContent        = today;", "const perfEl = document.getElementById('perf-date'); if(perfEl) perfEl.textContent = today;")

with open("dashboard/app.js", "w") as f:
    f.write(app_js)

print("Patched init in app.js")
