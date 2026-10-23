# CRM Cleanup Assistant

An AI assistant that keeps a sales CRM clean. Upload contacts and it:

- **Finds duplicate contacts** using fuzzy matching on name, company, email domain, and phone, then lets you merge or dismiss each pair.
- **Validates data**, flagging missing or invalid emails and incomplete phone numbers.
- **Categorizes leads** as Hot, Warm, Cold, Existing customer, or Not a fit.
- **Summarizes each contact's interaction history** in one sentence with the next step.

Categorization and summaries use Claude when an `ANTHROPIC_API_KEY` is set. Without a key, a rules-based fallback runs, so the demo works offline.

**Stack:** Python, FastAPI, PostgreSQL (SQLAlchemy), Claude API, Docker. It can be deployed to AWS.

---

## Run it locally (no setup)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs, then:

1. **POST /contacts/import**: upload `sample_data/contacts.csv`
2. **POST /analyze**: validates, categorizes, and finds duplicates
3. Open http://localhost:8000/ to see the dashboard

This mode uses a local SQLite file, so you don't need a database server.

## Run it with PostgreSQL (Docker)

```bash
docker compose up --build
```

This starts the API and a Postgres 16 database. To use Claude, run `export ANTHROPIC_API_KEY=sk-ant-...` before `docker compose up`.

## Run the tests

```bash
pytest -q
```

To run the tests against Postgres, set `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname` first.

---

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/contacts/import` | Upload a CSV (`name, email, company, phone, notes`). `replace=false` appends instead of replacing. |
| GET | `/contacts` | List contacts. Optional `?category=Hot`. |
| POST | `/analyze` | Validate, categorize, summarize, and detect duplicates. Returns a report. |
| GET | `/duplicates` | Pending duplicate pairs with score and reason. |
| POST | `/duplicates/{id}/merge?keep=a` | Merge a pair. Keeps record `a` or `b` and folds in the other's details and notes. |
| POST | `/duplicates/{id}/dismiss` | Mark a pair as not a duplicate. |
| GET | `/report` | Counts by category, data issues, and pending duplicates. |
| GET | `/` | Read-only dashboard for demos. |

## Settings (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./crm.db` | Database connection string |
| `ANTHROPIC_API_KEY` | (empty) | Turns on Claude for categorization and summaries |
| `CLAUDE_MODEL` | `claude-haiku-5-5` | Which Claude model to use |
| `DUPLICATE_THRESHOLD` | `85` | Score (0–100) at which a pair is flagged |

---

## Deploy to AWS (one EC2 server)

This is the simplest AWS setup: one small server running the app and Postgres with Docker Compose. It's enough for a demo or a small client.

1. **Launch a server.** In the AWS console, go to EC2, then Launch instance:
   - Image: Amazon Linux 2023
   - Type: `t3.small` (a `t3.micro` also works for a demo)
   - Key pair: create one and download the `.pem` file
   - Security group: allow SSH (port 22) from your IP, and port 8000 from anywhere
2. **Connect to the server:**
   ```bash
   ssh -i your-key.pem ec2-user@<public-ip>
   ```
3. **Install Docker and Git:**
   ```bash
   sudo dnf install -y docker git
   sudo systemctl enable --now docker
   sudo usermod -aG docker ec2-user && newgrp docker
   sudo mkdir -p /usr/local/lib/docker/cli-plugins
   sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
     -o /usr/local/lib/docker/cli-plugins/docker-compose
   sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
   ```
4. **Get the code onto the server.** Either `git clone` your GitHub repo, or copy the folder up with `scp -r`.
5. **Start it:**
   ```bash
   cd crm-cleanup-assistant
   export ANTHROPIC_API_KEY=sk-ant-...   # optional
   docker compose up -d --build
   ```
6. Open `http://<public-ip>:8000/docs`.

**For a real client:** move the database to Amazon RDS for PostgreSQL and set `DATABASE_URL` to the RDS endpoint. Put the API key in AWS Secrets Manager instead of the shell, and put HTTPS in front with a load balancer or Caddy. Before handing it over, change the Postgres password in `docker-compose.yml`. Stop the instance when you're not using it to avoid charges.

---

## Connecting a real CRM

The CSV import stands in for a CRM connection. For a client, add a small module that pulls contacts from their CRM's REST API (HubSpot, Salesforce, or Pipedrive) into the `contacts` table. After a person approves a merge or category, push it back through the same API. The cleaning and AI logic doesn't change.
