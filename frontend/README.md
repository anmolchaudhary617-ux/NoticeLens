# NoticeLens frontend

## Local development

Install the locked dependencies and start Vite:

```powershell
npm ci
npm run dev
```

During local development the frontend uses `http://localhost:8000` for the FastAPI
backend by default. Keep FastAPI and Ollama running locally to analyze notices.
To use a different API URL, set `VITE_API_URL` in a local Vite environment file;
Vite environment values are embedded in the public frontend build, so do not put
secrets in them.

## GitHub Pages

The production build uses `/NoticeLens/` as its base path and is deployed from
`frontend/dist` by `.github/workflows/deploy.yml`. On GitHub, select **Settings →
Pages → Build and deployment → Source → GitHub Actions**. Push to `main` or run
the deployment workflow manually to publish the site.

GitHub Pages hosts only the frontend. With no production API URL configured, the
site does not make requests to a visitor's `localhost`; it explains that AI
analysis requires the local backend and is unavailable to other visitors.
FastAPI and Ollama remain on the machine running them.
