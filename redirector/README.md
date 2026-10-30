# Redirector de invitaciones ASURA

Página mínima que convierte un enlace normal (`https://…`) en un enlace
profundo de Roblox:

```
https://TU-DOMINIO/join/<jobId>
        ↓
roblox://placeId=13358463560&gameInstanceId=<jobId>
```

## Por qué hace falta

Discord solo permite `http/https` en los botones. El protocolo `roblox://`
abre el cliente directamente (usa su sesión, sin login web), que es mucho más
fiable que `roblox.com/games/start` para entrar a un servidor exacto.

El redirector es solo un puente: no guarda nada, no usa cookies y no habla con
ningún servicio.

## Contenido

| Archivo | Para qué |
|---|---|
| `index.html` | La página. Lee el `jobId` de la URL y redirige. |
| `_redirects` | Regla para Netlify y Cloudflare Pages. |
| `vercel.json` | Regla para Vercel. |

## Desplegar (elige una)

### Opción A — Netlify Drop (la más rápida, sin cuenta al principio)

1. Entra en <https://app.netlify.com/drop>.
2. Arrastra **la carpeta `redirector`** completa.
3. Netlify te da una URL tipo `https://random-name-123.netlify.app`.
4. Prueba: `https://random-name-123.netlify.app/join/90fdd939-05ca-4ed0-9fe6-5d53e712d48d`.

> Netlify Drop procesa `_redirects` automáticamente. Si el enlace `/join/...`
> diera 404, revisa que subiste la carpeta y no solo el `index.html`.

### Opción B — Cloudflare Pages

1. <https://dash.cloudflare.com> → **Workers & Pages** → **Create** → **Pages**
   → **Upload assets**.
2. Sube el contenido de `redirector`.
3. La URL queda como `https://tu-proyecto.pages.dev`.

### Opción C — Vercel

1. `npm i -g vercel`
2. Dentro de `redirector/`: `vercel`
3. La URL queda como `https://tu-proyecto.vercel.app`.

## Configurar el bot

Añade al `.env`:

```env
INVITE_BASE_URL=https://tu-dominio.netlify.app/join
```

Sin barra final. Si la variable está vacía, el bot vuelve solo al enlace
oficial de `roblox.com`, así que no se rompe nada.

Reinicia el bot. Los enlaces nuevos saldrán como
`https://tu-dominio.netlify.app/join/<jobId>`.

## Probar sin esperar una alerta

```bash
python probar_alerta.py RIFT --solo-imagen
```

Para comprobar el botón de verdad necesitas un `jobId` real (de los logs del
bot o del API de Roblox):

```bash
python probar_alerta.py RIFT --servidor 90fdd939-05ca-4ed0-9fe6-5d53e712d48d
```

## Notas

- El `placeId` está en `index.html` (`var PLACE_ID`). Si cambias de juego,
  cámbialo ahí y en `configuracion/config.py`.
- La página valida que el ID tenga forma de UUID; si no, muestra un aviso en
  vez de intentar abrir Roblox.
- El intento automático puede bloquearlo el navegador; por eso hay un botón
  grande «Abrir Roblox» y un enlace alternativo por la web.
- En navegadores dentro de apps (Discord móvil, Instagram…) los enlaces
  `roblox://` a veces se bloquean. Ahí funciona el botón «Abrir en el
  navegador».
- Si prefieres no desplegar nada, deja `INVITE_BASE_URL` vacío: el bot usará
  `roblox.com/games/start` (funciona, pero exige sesión web y es menos
  fiable).
