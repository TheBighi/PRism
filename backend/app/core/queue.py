from arq.connections import ArqRedis, RedisSettings, create_pool

ANALYZE_PR_JOB = "analyze_pr"


async def get_queue() -> ArqRedis:
    redis = await create_pool(RedisSettings(host="localhost", port=6379))
    return redis


async def enqueue_pr_analysis(queue: ArqRedis, pull_request_id: int):
    await queue.enqueue_job(ANALYZE_PR_JOB, pull_request_id)
