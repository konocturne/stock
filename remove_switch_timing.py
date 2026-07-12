import re

with open("dashboard/app.js", "r") as f:
    app_js = f.read()

# Remove window.switchTiming entirely
app_js = re.sub(r'window\.switchTiming\s*=\s*function\(timing\)\s*\{.*?\};\n', '', app_js, flags=re.DOTALL)

with open("dashboard/app.js", "w") as f:
    f.write(app_js)

print("Removed switchTiming from app.js")
