import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AuthContext
from app.database import Base
from app.models import IgnoredRepository, Repository, User
from app.routers import repos as repos_router


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_repository_can_be_ignored_and_restored(monkeypatch):
    db = make_db()
    user = User(id=1, github_id=10, login="octocat")
    repo = Repository(
        id=1,
        github_id=100,
        owner="octocat",
        name="project",
        full_name="octocat/project",
    )
    db.add_all([user, repo])
    db.commit()
    auth = AuthContext(user=user, access_token="token")

    async def allowed_repositories(_auth):
        return {repo.github_id}

    monkeypatch.setattr(repos_router, "github_repository_ids", allowed_repositories)

    assert [item["id"] for item in asyncio.run(repos_router.list_repos(db, auth))] == [repo.id]

    response = repos_router.ignore_repo(repo.id, db, auth, repo)
    assert response.status_code == 204
    assert asyncio.run(repos_router.list_repos(db, auth)) == []
    assert [item["id"] for item in asyncio.run(repos_router.list_ignored_repos(db, auth))] == [repo.id]

    response = repos_router.restore_repo(repo.id, db, auth, repo)
    assert response.status_code == 204
    assert [item["id"] for item in asyncio.run(repos_router.list_repos(db, auth))] == [repo.id]
    assert asyncio.run(repos_router.list_ignored_repos(db, auth)) == []


def test_ignored_repository_is_scoped_to_user(monkeypatch):
    db = make_db()
    first_user = User(id=1, github_id=10, login="first")
    second_user = User(id=2, github_id=20, login="second")
    repo = Repository(
        id=1,
        github_id=100,
        owner="team",
        name="project",
        full_name="team/project",
    )
    db.add_all([first_user, second_user, repo])
    db.add(IgnoredRepository(user_id=first_user.id, repository_id=repo.id))
    db.commit()

    async def allowed_repositories(_auth):
        return {repo.github_id}

    monkeypatch.setattr(repos_router, "github_repository_ids", allowed_repositories)

    first_auth = AuthContext(user=first_user, access_token="token")
    second_auth = AuthContext(user=second_user, access_token="token")
    assert asyncio.run(repos_router.list_repos(db, first_auth)) == []
    assert [item["id"] for item in asyncio.run(repos_router.list_repos(db, second_auth))] == [repo.id]
