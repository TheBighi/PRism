from arq.connections import RedisSettings


async def analyze_pr(ctx, pull_request_id: int):
    print(f"Analyzing PR {pull_request_id}")


class WorkerSettings:
    functions = [analyze_pr]

    redis_settings = RedisSettings(
        host="localhost",
        port=6379,
    )