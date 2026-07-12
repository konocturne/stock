import re

with open("dashboard/index.html", "r") as f:
    html = f.read()

# Remove the timing-switch-panel block completely
html = re.sub(r'<!-- 時間帯切り替えスイッチパネル -->.*?</div>\s*</div>\s*<div class="container"', '<div class="container"', html, flags=re.DOTALL)

with open("dashboard/index.html", "w") as f:
    f.write(html)

print("Removed timing switch from index.html")
