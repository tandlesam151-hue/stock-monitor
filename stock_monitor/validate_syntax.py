"""
Quick syntax and import validation
"""

import ast
import sys
import os

# Ensure unicode (✓, emoji) prints correctly on Windows consoles (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def validate_python_file(filepath):
    """Check if Python file has valid syntax"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        return True, "OK"
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def main():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    files = [
        "config.py",
        "fetcher.py",
        "indicators.py",
        "patterns.py",
        "alert_engine.py",
        "notifier.py",
        "state.py",
        "main.py",
    ]
    
    print("Validating Python Syntax...\n")
    
    all_valid = True
    for filename in files:
        filepath = os.path.join(script_dir, filename)
        valid, message = validate_python_file(filepath)
        status = "✓" if valid else "✗"
        print(f"{status} {filename:20} - {message}")
        if not valid:
            all_valid = False
    
    if all_valid:
        print("\n✓ All files have valid Python syntax!")
        return 0
    else:
        print("\n✗ Some files have syntax errors!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
