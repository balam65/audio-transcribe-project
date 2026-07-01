import re

def fix_css():
    with open("frontend/css/styles.css", "r") as f:
        content = f.read()

    # 1. Replace muddy dark background colors that break light mode
    muddy_backgrounds = [
        r'rgba\(11,\s*3,\s*4,\s*0\.5\)',
        r'rgba\(25,\s*10,\s*10,\s*0\.35\)',
        r'rgba\(25,\s*10,\s*10,\s*0\.4\)',
        r'rgba\(25,\s*10,\s*10,\s*0\.45\)',
        r'rgba\(11,\s*3,\s*4,\s*0\.98\)',
        r'rgba\(11,\s*3,\s*4,\s*0\.94\)',
        r'rgba\(41,\s*21,\s*14,\s*0\.94\)'
    ]
    
    for mb in muddy_backgrounds:
        content = re.sub(mb, 'var(--bg-2)', content, flags=re.IGNORECASE)

    # 2. Fix the mistaken `background: var(--border-soft)` 
    # This was making everything flat and outline-colored.
    content = re.sub(r'background:\s*var\(--border-soft\);', r'background: var(--bg-1);', content, flags=re.IGNORECASE)

    # 3. Replace white-based translucent backgrounds which are invisible in light mode
    # Replace them with var(--bg-5) which is a subtle blue overlay
    white_translucents = [
        r'rgba\(255,\s*255,\s*255,\s*0\.025\)',
        r'rgba\(255,\s*255,\s*255,\s*0\.035\)'
    ]
    
    for wt in white_translucents:
        content = re.sub(wt, 'var(--bg-5)', content, flags=re.IGNORECASE)

    with open("frontend/css/styles.css", "w") as f:
        f.write(content)

if __name__ == "__main__":
    fix_css()
