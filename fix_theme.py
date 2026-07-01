import re

with open("frontend/css/styles.css", "r") as f:
    content = f.read()

# Replace hardcoded red/coral gradients and backgrounds with standard CSS variables
content = re.sub(r'rgba\(255,\s*45,\s*45,\s*([0-9.]+)\)', r'rgba(59, 130, 246, \1)', content) # Red -> Blue
content = re.sub(r'rgba\(255,\s*122,\s*89,\s*([0-9.]+)\)', r'rgba(139, 92, 246, \1)', content) # Coral -> Indigo
content = re.sub(r'rgba\(128,\s*0,\s*0,\s*([0-9.]+)\)', r'rgba(30, 64, 175, \1)', content) # Dark red -> Dark blue
content = re.sub(r'#ff2a2a|#ff3c2a|#ff7a59', '#3b82f6', content)

# Fix meeting item layout
content = content.replace(
    '.meeting-item {\n  display: flex;\n  justify-content: space-between;\n  gap: 12px;',
    '.meeting-item {\n  display: flex;\n  flex-direction: column;\n  gap: 12px;'
)

with open("frontend/css/styles.css", "w") as f:
    f.write(content)

