# Whisper GUI

## Frontend

The `frontend/` folder contains a Vite + React (TypeScript) single-page application that can be used to submit transcription jobs to the backend API.

### Development

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API calls to the backend defined by `VITE_BACKEND_URL` (defaults to `http://localhost:8000`). Requests to `/api` and `/jobs` are forwarded automatically.

### Production build

```bash
cd frontend
npm install
npm run build
npm run preview
```

## Hugging Face token

Create a read access token at <https://huggingface.co/settings/tokens> and expose it to the backend as the `HF_TOKEN` environment variable (or pass the flag supported by your backend runtime). Restart the backend after updating the token so that the new credentials are picked up.
