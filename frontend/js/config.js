/* MEDD Maharashtra 2.0 — frontend configuration.
 * NO credentials, keys or database details belong in frontend files. The API is served from the same origin
 * by FastAPI; set API_BASE only if the frontend is hosted separately (and add that origin to CORS_ORIGINS). */
window.MEDD_CONFIG = {
  API_BASE: '/api/v1',
  APP_TITLE: 'MEDD Maharashtra',
  REQUEST_TIMEOUT_MS: 60000,
};
