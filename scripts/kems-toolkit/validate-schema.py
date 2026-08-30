#!/usr/bin/env python3
"""验证 _entities/ 下的实体是否符合 meta-model/schema.json 中定义的约束。"""
import json, os, re, sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_FILE = os.path.join(BASE, '_meta-model', 'schema.json')

def load_schema():
    with open(SCHEMA_FILE) as f:
        return json.load(f)

def check_entity(filepath, entity_type, schema):
    """Check a single entity .md file against its type constraints."""
    with open(filepath) as f:
        content = f.read()
    
    type_def = None
    if entity_type in schema.get('entity_types', {}):
        type_def = schema['entity_types'][entity_type]
    elif entity_type in schema.get('base_types', {}):
        type_def = {'extends': entity_type, 'additional_properties': []}
    else:
        return [(f"Unknown type: {entity_type}", 'error')]
    
    base_name = type_def['extends']
    base_def = schema['base_types'].get(base_name, {})
    base_props = base_def.get('properties', {})
    
    issues = []
    # Check base required properties exist as markdown fields
    for prop, defn in base_props.items():
        constraints = defn.get('constraints', [])
        if 'required' in constraints:
            # Look for the field in the markdown
            # Simple heuristic: check if the field name appears as a markdown list item
            pattern = rf'^\s*[-*]\s+{prop}\s*[:：]' 
            if not re.search(pattern, content, re.MULTILINE):
                issues.append((f"{entity_type}: missing required field '{prop}'", 'error'))
    
    # Check trust_level values
    trust_match = re.search(r'trust_level.*?[:：]\s*(\w+)', content)
    if trust_match:
        trust_def = base_props.get('trust_level', {})
        valid = trust_def.get('values', [])
        if valid and trust_match.group(1) not in valid:
            issues.append((f"{entity_type}: invalid trust_level '{trust_match.group(1)}'", 'error'))
    
    return issues

def main():
    schema = load_schema()
    entities_dir = os.path.join(BASE, '_entities')
    
    type_map = {
        'persons.md': 'Person',
        'organizations.md': 'Organization',
        'projects.md': 'Project',
        'events.md': 'Event',
        'documents.md': 'Document'
    }
    
    all_issues = []
    checked = 0
    for fname, etype in type_map.items():
        fpath = os.path.join(entities_dir, fname)
        if not os.path.exists(fpath):
            continue
        # Count non-template entries
        with open(fpath) as f:
            entries = len(re.findall(r'^##\s+\[', f.read(), re.MULTILINE))
        checked += 1
        # Schema check on the file itself (template format)
        issues = check_entity(fpath, etype, schema)
        for msg, sev in issues:
            all_issues.append((f"{fname}: {msg}", sev))
    
    errors = [i for i in all_issues if i[1] == 'error']
    warnings = [i for i in all_issues if i[1] == 'warning']
    
    print(f"=== KEMS Schema Validation ===")
    print(f"Schema: {schema['version']}")
    print(f"Entities checked: {checked}/{len(type_map)} files")
    print(f"Errors: {len(errors)} | Warnings: {len(warnings)}")
    
    if errors:
        print(f"\n🔴 Errors:")
        for msg, _ in errors: print(f"  {msg}")
    if warnings:
        print(f"\n⚠️  Warnings:")
        for msg, _ in warnings: print(f"  {msg}")
    if not errors and not warnings:
        print("✅ All schema constraints satisfied")
    
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
