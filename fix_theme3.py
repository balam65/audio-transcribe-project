import re

def fix_css():
    with open("frontend/css/styles.css", "r") as f:
        content = f.read()

    # Map light/pale colors to standard text/accent variables so they adapt to light/dark themes
    replacements = [
        (r'color:\s*#9eb7e1;?', 'color: var(--text-2);'),
        (r'color:\s*#dfe9ff;?', 'color: var(--text-0);'),
        (r'color:\s*#c0cbdf;?', 'color: var(--text-1);'),
        (r'color:\s*#7e8aa2;?', 'color: var(--text-3);'),
        (r'color:\s*#c2d1e6;?', 'color: var(--text-1);'),
        
        # Pastel accents
        (r'color:\s*#ffd3a0;?', 'color: var(--accent-warning);'),
        (r'color:\s*#ffe0b8;?', 'color: var(--accent-warning);'),
        (r'color:\s*#ffd79e;?', 'color: var(--accent-warning);'),
        (r'color:\s*#ffd9a4;?', 'color: var(--accent-warning);'),
        (r'color:\s*#ffe3b0;?', 'color: var(--accent-warning);'),
        
        (r'color:\s*#baf6d1;?', 'color: var(--accent-success);'),
        
        (r'color:\s*#ff9e9e;?', 'color: var(--accent-danger);'),
        (r'color:\s*#ff7878;?', 'color: var(--accent-danger);'),
        (r'color:\s*#ffd2d6;?', 'color: var(--accent-danger);'),
        (r'color:\s*#ffd3d9;?', 'color: var(--accent-danger);'),
        
        (r'color:\s*#c6f7ff;?', 'color: var(--accent-cyan);'),
        
        (r'color:\s*#e2d7d7;?', 'color: var(--text-2);'),
    ]

    for pattern, repl in replacements:
        content = re.sub(pattern, repl, content, flags=re.IGNORECASE)

    # Fix the app title which is pure white
    content = re.sub(r'(\.app-title-group\s+h1\s*\{[^}]*)color:\s*#ffffff;?', r'\1color: var(--text-0);', content, flags=re.IGNORECASE)

    # Fix summarizer drawer hardcoded gradients
    content = re.sub(
        r'(\.summarizer-drawer\s*\{[^}]*)background:[^;]+;',
        r'\1background: var(--bg-1);',
        content,
        flags=re.IGNORECASE
    )

    # Fix any remaining linear-gradient or radial-gradient backgrounds on structural containers
    content = re.sub(
        r'(\.left-rail\s*\{[^}]*)background:[^;]+;',
        r'\1background: var(--bg-1);',
        content,
        flags=re.IGNORECASE
    )
    
    content = re.sub(
        r'(\.workspace-grid\s*\{[^}]*)background:[^;]+;',
        r'\1background: transparent;',
        content,
        flags=re.IGNORECASE
    )

    with open("frontend/css/styles.css", "w") as f:
        f.write(content)

if __name__ == "__main__":
    fix_css()
