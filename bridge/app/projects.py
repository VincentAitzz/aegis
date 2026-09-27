from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Project:
    alias: str
    root: Path
    verify: dict = field(default_factory=dict)
    neon_project: str = ''
    neon_branch: str = 'dev'
    strategy: str = 'psql'
    can_read: bool = True
    can_migrate: bool = False
    can_branch: bool = False
    note: str = ''

PROJECTS: dict[str, Project] = {
    'aegis': Project(
        alias='aegis',
        root=Path('/RUTA/AL/WORKSPACE/aegis'),
        # No hay typechecker, pero sí un chequeo que vale: importar el paquete.
        # Sin esto el agente escribe Python sin que nada le diga que un símbolo
        # sin importar solo falla al importar, no al escribir.
        verify={
            'check': ['bridge/.venv/bin/python', 'bridge/bin/check-imports.py'],
            'test': ['bridge/.venv/bin/python', '-m', 'unittest', 'discover',
                      '-s', 'bridge/tests', '-q'],
        },
        neon_project='el-proyecto-de-neon-aegis',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
        note='base propia de Aegis. Sin esquema: la memoria sigue local.'
    ),
    'portafolio': Project(
        alias='portafolio',
        root=Path('/RUTA/AL/WORKSPACE/web/portafolio/'),
        verify={
            'check': ['node_modules/.bin/tsc', '--noEmit', '-p', 'tsconfig.json'],
            'test': ['node_modules/.bin/vitest', 'run'],
            'build': ['node_modules/.bin/astro', 'build']
        },
        neon_project='el-proyecto-de-neon-aegis',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=True,
        can_branch=True,
    ),
    'compra-unida': Project(
        alias='compra-unida',
        root=Path('/RUTA/AL/WORKSPACE/apps//compra-unida'),
        verify={
            'check': ['node_modules/.bin/tsc', '--noEmit'],
            'test': ['npm test']
        },
        neon_project='el-proyecto-de-neon-del-cliente',
        neon_branch='dev',
        strategy='drizzle',
        can_read=True,
        can_migrate=False,
        can_branch=True,
        note='journal de drizzle vacío con 24 tablas con datos en production y dev: db:migrate intentaría recrearlas.'
    ),
    'trazeurs': Project(
        alias='trazeurs',
        root=Path('/RUTA/AL/WORKSPACE/mobile//trazeurs'),
        verify={
            'check': ['/RUTA/A/FLUTTER/bin/flutter', 'analyze', '--no-pub'],
            'test': ['/RUTA/A/FLUTTER/bin/flutter', 'test', '--no-pub']
        },
        neon_project='',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
    ),
    'recepcion-persa': Project(
        alias='recepcion-persa',
        root=Path('/RUTA/AL/WORKSPACE/apps//recepcion_persa'),
        verify={
            'check': ['python3', '-m', 'compileall', '-q', '.'],
            'test': ['python3', '-m', 'pytest', '-q']
        },
        neon_project='',
        neon_branch='dev',
        strategy='psql',
        can_read=True,
        can_migrate=False,
        can_branch=False,
    )
}

def project(alias: str) -> Project:
    if alias not in PROJECTS:
        raise ValueError(f"proyecto no registrado: {alias} "
                         f"(conocidos: {', '.join(sorted(PROJECTS))})")
    return PROJECTS[alias]


def neon_entry(alias: str) -> dict:
    p = project(alias)
    return {'neon_project': p.neon_project, 'neon_branch': p.neon_branch,
    }