from sqlalchemy import text


async def close_for_rectification(db, version_id):
    await db.execute(text("SELECT close_sanction_cases_for_rectification(:version)"), {"version": version_id})
