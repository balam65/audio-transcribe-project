import re

def fix_css():
    with open("frontend/css/styles.css", "r") as f:
        content = f.read()

    # Background hex colors
    replacements = [
        (r'#060608', 'var(--bg-0)'),
        (r'#0b0b0e', 'var(--bg-1)'),
        (r'#121215', 'var(--bg-2)'),
        (r'#080c14', 'var(--bg-1)'),
        (r'#050505', 'var(--bg-0)'),
        (r'#090e16', 'var(--bg-1)'),
        
        # Background rgba colors
        (r'rgba\(12,\s*12,\s*15,\s*0\.88\)', 'var(--bg-3)'),
        (r'rgba\(18,\s*18,\s*22,\s*0\.94\)', 'var(--bg-4)'),
        (r'rgba\(14,\s*14,\s*18,\s*[0-9.]+\)', 'var(--bg-3)'),
        (r'rgba\(18,\s*18,\s*22,\s*[0-9.]+\)', 'var(--bg-4)'),
        (r'rgba\(9,\s*14,\s*22,\s*[0-9.]+\)', 'var(--bg-1)'),
        (r'rgba\(6,\s*10,\s*16,\s*[0-9.]+\)', 'var(--bg-1)'),
        (r'rgba\(8,\s*12,\s*20,\s*[0-9.]+\)', 'var(--bg-2)'),
        (r'rgba\(0,\s*0,\s*0,\s*0\.56\)', 'var(--bg-3)'),
        (r'rgba\(46,\s*52,\s*72,\s*0\.18\)', 'var(--border-strong)'),
        (r'rgba\(4,\s*5,\s*8,\s*0\.98\)', 'var(--bg-0)'),
        
        # Text colors
        (r'#f5f5f7', 'var(--text-0)'),
        (r'#d2d2d7', 'var(--text-1)'),
        (r'#929297', 'var(--text-2)'),
        (r'#626267', 'var(--text-3)'),
        
        # Border colors
        (r'rgba\(255,\s*255,\s*255,\s*0\.0[2-9]\)', 'var(--border-soft)'),
        (r'rgba\(255,\s*255,\s*255,\s*0\.1[0-9]\)', 'var(--border-strong)'),
    ]

    for pattern, repl in replacements:
        content = re.sub(pattern, repl, content, flags=re.IGNORECASE)

    # Clean up shadows that might be unreadable in light mode
    # We map them to var(--shadow-sm), md, lg
    content = re.sub(r'0\s+24px\s+70px\s+rgba\(0,\s*0,\s*0,\s*0\.65\)', 'var(--shadow-lg)', content)
    content = re.sub(r'0\s+14px\s+42px\s+rgba\(0,\s*0,\s*0,\s*0\.55\)', 'var(--shadow-md)', content)

    with open("frontend/css/styles.css", "w") as f:
        f.write(content)

if __name__ == "__main__":
    fix_css()
