"""Shared form parsing and YAML engine entry point for both output lifetimes."""
import json
from core import parser, yaml_utils


def parse_form_nodes(form, country_lookup=None):
    """Shared input path for Preview and Generate; never trust a cached preview."""
    text = form.get('batch_nodes', '').strip()
    try:
        rows = json.loads(form.get('aux_nodes', '[]'))
        overrides = json.loads(form.get('node_overrides', '{}'))
        if not isinstance(rows, list) or not isinstance(overrides, dict):
            raise ValueError
        for override in overrides.values():
            if not isinstance(override, dict) or any(k not in ('country', 'name') or not isinstance(v, str)
                                                    for k, v in override.items()):
                raise ValueError
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('country', 'name', 'link')):
                raise ValueError
            country, name, link = (row[k].strip() for k in ('country', 'name', 'link'))
            if not any((country, name, link)):
                continue
            if not link or not name or any(c in country + name + link for c in ('\n', '\r')) or '|' in country + name:
                raise ValueError
            text += '\n' + (country + '|' if country else '') + name + '|' + link
    except (ValueError, TypeError):
        raise ValueError('辅助节点或手工修改格式无效，请检查名称、国家及链接。') from None
    country, name, link = (form.get('single_' + k, '').strip() for k in ('country', 'name', 'link'))
    if country and name and link:
        text += f'\n{country}|{name}|{link}'
    return parser.parse_batch_nodes(text, overrides, country_lookup)


def generate(input_path, output_dir, backup_dir, parsed, special_groups, policy_config=None, group_transform=None, *, node_update_mode='replace'):
    return yaml_utils.process_yaml_config(
        input_path=str(input_path), output_dir=str(output_dir), backup_dir=str(backup_dir),
        new_nodes=parsed["nodes"], countries=parsed["countries"], special_groups=special_groups, policy_config=policy_config, group_transform=group_transform, node_update_mode=node_update_mode)
