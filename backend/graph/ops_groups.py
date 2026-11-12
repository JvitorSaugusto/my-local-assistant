'''Agrupa as alterações não commitadas em commits coerentes (sem LLM).'''
from __future__ import annotations

import re
from pathlib import Path

try:
    from . import ops_core as core
except ImportError:  # carregado fora do pacote (testes isolados)
    import importlib.util

    _spec = importlib.util.spec_from_file_location('ops_core', Path(__file__).with_name('ops_core.py'))
    core = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(core)

MAX_GROUP = 8
_TEST_DIRS = {'tests', 'test', '__tests__'}


def _is_doc(path):
    low = path.lower()
    return low.startswith('docs/') or low.endswith('.md')


def _dir(path):
    parts = path.split('/')[:-1]
    while parts and parts[-1] in _TEST_DIRS:
        parts.pop()
    return '/'.join(parts) or '(raiz)'


def _feature(path):
    stem = path.rsplit('/', 1)[-1].rsplit('.', 1)[0].lower()
    stem = re.sub(r'^test_|_test$|[.]test$|[.]spec$', '', stem)
    return re.split(r'[_.-]', stem)[0] or stem


def group_changes(items, max_group=MAX_GROUP):
    '''Devolve (grupos, ignorados). Regras: testes ficam com o código da mesma pasta,
    docs vão juntos, pasta grande se divide por prefixo do nome, nenhum grupo passa de max_group.'''
    usable = [i for i in items if not core.is_secret_path(i['path'])]
    skipped = [i['path'] for i in items if core.is_secret_path(i['path'])]
    by_dir = {}
    for item in usable:
        key = 'docs' if _is_doc(item['path']) else _dir(item['path'])
        by_dir.setdefault(key, []).append(item)
    buckets = []
    for key, members in by_dir.items():
        if len(members) <= max_group:
            buckets.append((key, members))
            continue
        by_feature = {}
        for item in members:
            by_feature.setdefault(_feature(item['path']), []).append(item)
        misc = []
        for feature, subset in by_feature.items():
            if len(subset) == 1:
                misc.extend(subset)
            else:
                buckets.append((f'{key} [{feature}]', subset))
        if misc:
            buckets.append((f'{key} [outros]', misc))
    groups = []
    for label, members in buckets:
        members = sorted(members, key=lambda i: i['path'])
        chunks = [members[n:n + max_group] for n in range(0, len(members), max_group)]
        for number, chunk in enumerate(chunks, 1):
            groups.append({
                'label': label if len(chunks) == 1 else f'{label} (parte {number})',
                'items': chunk,
                'paths': [i['path'] for i in chunk],
                'added': sum(i['added'] for i in chunk),
                'removed': sum(i['removed'] for i in chunk),
            })
    groups.sort(key=lambda g: (g['label'].startswith('docs'), g['label']))
    return groups, skipped


def format_groups(groups, skipped=(), branch=''):
    if not groups:
        return 'Nenhum arquivo com alterações não commitadas.'
    total = sum(len(g['paths']) for g in groups)
    head = f'{total} arquivo(s) em {len(groups)} grupo(s) sugerido(s)' + (f" na branch '{branch}':" if branch else ':')
    lines = [head]
    for number, group in enumerate(groups, 1):
        lines.append('')
        lines.append(f"Grupo {number}: {group['label']} — {len(group['paths'])} arquivo(s), +{group['added']} -{group['removed']}")
        for i in group['items']:
            lines.append(f"  - {i['path']} ({i['status']}, +{i['added']} -{i['removed']})")
    if skipped:
        lines.append('')
        lines.append('Não entram (parecem segredos): ' + ', '.join(skipped))
    return '\n'.join(lines)


def commit_groups(root, groups):
    '''Um commit por grupo. Valida tudo antes: se qualquer grupo for inválido, nenhum commit é feito.'''
    root = Path(root)
    if not isinstance(groups, list) or not groups:
        return 'ERRO: nenhum grupo informado.'
    if not core.is_repo(root):
        return 'ERRO: não é um repositório git.'
    branch = core.current_branch(root)
    if branch in core.PROTECTED_BRANCHES:
        return f"ERRO: você está na branch protegida '{branch}'. Troque para uma branch de trabalho antes."
    changes = {i['path']: i for i in core.git_changes(root)}
    plan, used = [], set()
    for number, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            return f'ERRO: grupo {number} inválido. Nenhum commit foi feito.'
        message = str(group.get('message') or '').strip()
        if not message:
            return f'ERRO: grupo {number} sem mensagem. Nenhum commit foi feito.'
        found, ambiguous, missing = core.resolve_names(changes.keys(), group.get('paths') or [])
        if ambiguous or missing:
            return core._problems_text(ambiguous, missing) + f' (grupo {number}; nenhum commit foi feito)'
        if not found:
            return f'ERRO: grupo {number} sem arquivos. Nenhum commit foi feito.'
        secrets = [p for p in found if core.is_secret_path(p)]
        if secrets:
            return 'ERRO: não commito arquivos que parecem segredos: ' + ', '.join(secrets) + '. Nenhum commit foi feito.'
        repeated = [p for p in found if p in used]
        if repeated:
            return 'ERRO: arquivo em mais de um grupo: ' + ', '.join(repeated) + '. Nenhum commit foi feito.'
        used.update(found)
        plan.append((found, message))
    lines, done = [], 0
    for found, message in plan:
        result = core.commit_paths(root, found, message)
        if result.startswith('ERRO'):
            lines.append(f'{result} Parei aqui; os grupos seguintes não foram commitados.')
            break
        lines.append(result.split(' Para desfazer')[0])
        done += 1
    left = [p for p in changes if p not in used]
    if left:
        lines.append(f'Ficaram sem commit ({len(left)}): ' + ', '.join(left[:15]))
    if done:
        lines.append(f'Para desfazer tudo: git reset --soft HEAD~{done}')
    return '\n'.join(lines)
