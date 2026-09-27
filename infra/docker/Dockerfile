# Aegis — imagen del sandbox de aislamiento del agente
# Cada comando que el agente ejecuta (escribir archivos, compilar, correr
# tests) ocurre DENTRO de este contenedor. Básica y despiadada: nada más que
# toolchains de build + git. Añade herramientas solo si un módulo lo exige.
FROM python:3.13-slim

# Toolchains mínimos para compilar/pruebas de módulos generados por el agente.
# - build-essential: gcc/make para C/C++ nativo (numpy, boost, etc.)
# - curl: descargas puntuales / diagnóstico
# - git: el agente versiona módulos que escribe dentro del sandbox
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      git \
 && rm -rf /var/lib/apt/lists/*

# Node 20 + npm opcional: descomenta si el agente genera módulos JS/TS.
# RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
#  && apt-get install -y nodejs \
#  && rm -rf /var/lib/apt/lists/*

# Directorio de trabajo por defecto: Hermes monta –v cwd:/workspace.
WORKDIR /workspace

CMD ["bash"]