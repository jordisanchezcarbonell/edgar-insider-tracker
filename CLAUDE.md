# Proyecto: edgar-insider-tracker

## Contexto
Estoy aprendiendo quantitative development y construyo este proyecto para mi portfolio de GitHub. Vengo de un perfil de coordinación de proyectos, tengo bases de programación pero NO soy experto. Quiero APRENDER construyendo, no solo recibir código terminado.

## Reglas de trabajo (importantes)
- Trabaja por fases pequeñas. No generes el proyecto entero de golpe.
- Antes de escribir código, explícame el plan y espera mi OK.
- Cuando escribas código, coméntame las decisiones de diseño no obvias.
- Si algo tiene varias formas de hacerse, dame las opciones y tu recomendación antes de elegir por mí.
- Prioriza código legible y simple sobre código "listo". Soy yo quien tiene que entenderlo y defenderlo en una entrevista técnica.
- Pregúntame cuando una decisión dependa de mi criterio.

## Objetivo del proyecto
Un pipeline en Python que descarga, parsea y analiza Forms 3/4/5 (insider trading) de SEC EDGAR, y muestra los resultados en una web Streamlit. NO es un proyecto de "predecir el mercado". Es un proyecto de ingesta y análisis riguroso de datos regulatorios reales, honesto sobre sus límites.

## Stack
- Python 3.11+
- Fuente de datos: API pública de data.sec.gov (sin API key)
- pandas para análisis
- SQLite para almacenamiento (NO PostgreSQL — quiero algo simple y portable)
- Streamlit para la visualización
- pytest para tests
- Estructura de repo limpia, con README, requirements.txt, .gitignore, LICENSE MIT
