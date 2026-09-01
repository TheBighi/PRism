# WORK IN PROGRESS

PRism - Evidence-driven engineering intelligence for pull requests

## GitHub OAuth setup

Create a GitHub OAuth App under **Settings -> Developer settings -> OAuth Apps**.

- Homepage URL: `http://localhost:5173`
- Authorization callback URL: `http://localhost:5173/api/auth/callback`

Add these values to `backend/.env`:

```dotenv
GITHUB_CLIENT_ID=your_oauth_app_client_id
GITHUB_AUTH_SECRET=your_oauth_app_client_secret
GITHUB_OAUTH_CALLBACK_URL=http://localhost:5173/api/auth/callback
FRONTEND_URL=http://localhost:5173
COOKIE_SECURE=false
```

OAuth is the only login method. The backend keeps an opaque session in an
HttpOnly cookie and only returns tracked repositories that GitHub lists as
owned by, collaborated on, or available through an organization to the user.
Use HTTPS and `COOKIE_SECURE=true` outside local development.
