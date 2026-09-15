# PRism

PRism is a tool for analyzing GitHub pull requests and showing useful information about the changes in one place.

It connects to GitHub, analyzes pull requests automatically, and gives each pull request a risk score together with information that can help developers review changes more easily.

> PRism is currently a work in progress.

## Features

* GitHub login
* Automatic pull request analysis
* Risk score from 0 to 100
* AI summary of pull request risks
* Security checks
* Linting checks
* Type checking
* Test results
* Test coverage changes
* Dependency changes
* Changed file statistics
* Pull request history
* GitHub check integration
* Automatic analysis through GitHub webhooks

## Images

![PRism screenshot 0](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism0.png)

![PRism screenshot 1](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism1.png)

![PRism screenshot 2](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism2.png)

![PRism screenshot 3](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism3.png)

![PRism screenshot 4](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism4.png)

![PRism screenshot 5](https://raw.githubusercontent.com/TheBighi/TheBighi/refs/heads/main/images/PRism5.png)

## How It Works

1. Sign in with your GitHub account.
2. Select a repository that PRism has access to.
3. PRism receives pull request updates from GitHub.
4. The pull request is analyzed in the background.
5. The results are shown in the PRism dashboard.
6. PRism gives the pull request a risk score and displays possible problems.

## Analysis

PRism looks at several parts of a pull request.

### Risk Score

Each pull request receives a risk score from `0` to `100`.

A higher score means the pull request may need more attention before it is merged.

### AI Analysis

PRism can generate a simple AI explanation containing:

* An overall risk level
* A summary of the pull request
* The most important risks
* Files related to those risks
* Recommended actions

### Code Checks

PRism can also show:

* Security findings
* Lint errors and warnings
* Type checking problems
* Test results
* Test coverage changes
* Dependency changes
* File additions and deletions

## Tech Stack

### Frontend

* React
* TypeScript
* Vite
* React Router
* Axios

### Backend

* Python
* FastAPI
* SQLAlchemy
* PostgreSQL
* Redis
* ARQ

### Other

* GitHub API
* GitHub Apps
* Docker
* AI models through Gemini or OpenRouter

## Project Structure

```text
PRism/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   ├── routers/
│   │   ├── workers/
│   │   ├── auth.py
│   │   ├── database.py
│   │   ├── main.py
│   │   └── models.py
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── App.tsx
│   │   └── api.ts
│   └── package.json
│
└── docker-compose.yml
```

## Running Locally

### 1. Clone the repository

```bash
git clone https://github.com/TheBighi/PRism.git
cd PRism
```

### 2. Start PostgreSQL and Redis

Docker Compose can start both services:

```bash
docker compose up -d
```

### 3. Set up the backend

```bash
cd backend

python -m venv .venv
```

Activate the virtual environment.

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Copy the environment file:

```bash
cp .env.example .env
```

On Windows you can use:

```powershell
copy .env.example .env
```

Then fill in the required GitHub, database, and AI settings inside `.env`.

GitHub login also requires:

```env
GITHUB_CLIENT_ID=
GITHUB_AUTH_SECRET=
```

### 4. Start the backend

From the `backend` folder:

```bash
uvicorn app.main:app --reload
```

The backend will run on:

```text
http://localhost:8000
```

### 5. Start the analysis workers

Open another terminal inside the `backend` folder:

```bash
python -m app.workers.run_all
```

These workers handle pull request analysis, AI explanations, and repository history.

### 6. Start the frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend will run on:

```text
http://localhost:5173
```

## GitHub Integration

PRism uses GitHub authentication and GitHub webhooks.

The webhook endpoint is:

```text
/github/webhook
```

GitHub sends pull request events to PRism. When a pull request is opened or updated, PRism can automatically start a new analysis.

## Development Status

PRism is still under development.

Features, analysis methods, and the user interface may change as the project grows.

## Author

Created by [TheBighi](https://github.com/TheBighi).
