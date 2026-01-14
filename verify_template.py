import sys
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

try:
    env = Environment(loader=FileSystemLoader(r'c:\Projeto\analise_operacional\templates'))
    # Try to parse the template
    template = env.get_template('mobile/dashboard.html')
    print("Template syntax is VALID.")
except TemplateSyntaxError as e:
    print(f"Template Syntax Error: {e}")
    print(f"Line: {e.lineno}")
    print(f"Message: {e.message}")
except Exception as e:
    print(f"Other Error: {e}")
