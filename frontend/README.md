# Frontend

The React 19 + Vite web app for NBA Season Predictor. It shows standings and Monte Carlo playoff and championship odds from the project's API. See the [main README](../README.md) for what the project does and how to run the whole stack.

## Develop

With the API running (`docker compose up -d --wait` from the repository root):

```bash
npm ci
npm run dev
```

Then open http://localhost:5173. In development the app calls the API at http://localhost:8000 (override with `VITE_API_BASE_URL`), and the API allows requests from port 5173 by default.

## Test, lint, and build

```bash
npm test
npm run lint
npm run build
```

In Docker, [Dockerfile](Dockerfile) builds the app and serves it with nginx, which forwards `/api` requests to the API ([nginx.conf](nginx.conf)).
