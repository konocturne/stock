import re

with open("dashboard/app.js", "r") as f:
    app_js = f.read()

old_hist = """function renderHistory(history) {
  const sec = document.getElementById('section-history');
  if (!history || !history.length) { sec.style.display = 'none'; return; }
  sec.style.display = '';
  document.getElementById('history-list').innerHTML = history.map((h, i) => {"""

new_hist = """function renderHistory(history) {
  const sec = document.getElementById('section-history');
  if (!sec) return;
  if (!history || !history.length) { sec.style.display = 'none'; return; }
  sec.style.display = '';
  document.getElementById('history-list').innerHTML = history.map((h, i) => {"""

app_js = app_js.replace(old_hist, new_hist)

with open("dashboard/app.js", "w") as f:
    f.write(app_js)

print("Patched renderHistory in app.js")
