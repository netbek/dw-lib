from collections.abc import Mapping, Sequence
from dagster import (
    AssetsDefinition,
    DagsterRunStatus,
    DefaultScheduleStatus,
    define_asset_job,
    RunConfig,
    RunRequest,
    RunsFilter,
    schedule,
    ScheduleEvaluationContext,
    SkipReason,
)
from dagster._core.definitions.target import ExecutableDefinition
from dagster_dbt.asset_utils import (
    build_dbt_asset_selection,
    DBT_DEFAULT_EXCLUDE,
    DBT_DEFAULT_SELECT,
    DBT_DEFAULT_SELECTOR,
)

# https://github.com/dagster-io/dagster/blob/1.12.19/python_modules/dagster/dagster/_core/storage/dagster_run.py#L110
NOT_FINISHED_STATUSES = [
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    # DagsterRunStatus.CANCELING,
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
]


def build_singleton_schedule(
    job: ExecutableDefinition,
    cron_schedule: str,
    schedule_name: str | None = None,
    tags: Mapping[str, str] | None = None,
    config: RunConfig | None = None,
    execution_timezone: str | None = None,
    default_status: DefaultScheduleStatus = DefaultScheduleStatus.STOPPED,
):
    """
    Returns a schedule that only triggers if no other instance of the job is running.

    Reference: https://docs.dagster.io/guides/operate/managing-concurrency/advanced
    """
    schedule_name = schedule_name or f"{job.name}_schedule"

    @schedule(
        name=schedule_name,
        job=job,
        cron_schedule=cron_schedule,
        execution_timezone=execution_timezone,
        default_status=default_status,
    )
    def _schedule(context: ScheduleEvaluationContext):
        # Find an unfinished run of the job
        runs = context.instance.get_runs(
            filters=RunsFilter(job_name=job.name, statuses=NOT_FINISHED_STATUSES), limit=1
        )

        if runs:
            return SkipReason(f"Skipping {job.name} because a run is already in progress.")

        return RunRequest(run_config=config, tags=tags)

    return _schedule


def build_singleton_schedule_from_dbt_selection(
    dbt_assets: Sequence[AssetsDefinition],
    job_name: str,
    cron_schedule: str,
    dbt_select: str = DBT_DEFAULT_SELECT,
    dbt_exclude: str | None = DBT_DEFAULT_EXCLUDE,
    dbt_selector: str = DBT_DEFAULT_SELECTOR,
    schedule_name: str | None = None,
    tags: Mapping[str, str] | None = None,
    config: RunConfig | None = None,
    execution_timezone: str | None = None,
    default_status: DefaultScheduleStatus = DefaultScheduleStatus.STOPPED,
):
    """
    Returns a schedule for dbt assets that only triggers if no other instance of the job is running.

    Based on https://github.com/dagster-io/dagster/blob/1.12.19/python_modules/libraries/dagster-dbt/dagster_dbt/asset_utils.py#L353
    """
    selection = build_dbt_asset_selection(
        dbt_assets,
        dbt_select=dbt_select,
        dbt_exclude=dbt_exclude or DBT_DEFAULT_EXCLUDE,
        dbt_selector=dbt_selector,
    )
    job = define_asset_job(
        name=job_name,
        selection=selection,
        config=config,
        tags=tags,
    )
    schedule_name = schedule_name or f"{job_name}_schedule"

    @schedule(
        name=schedule_name,
        job=job,
        cron_schedule=cron_schedule,
        execution_timezone=execution_timezone,
        default_status=default_status,
    )
    def _schedule(context: ScheduleEvaluationContext):
        # Find an unfinished run of the job
        runs = context.instance.get_runs(
            filters=RunsFilter(job_name=job.name, statuses=NOT_FINISHED_STATUSES), limit=1
        )

        if runs:
            return SkipReason(f"Skipping {job.name} because a run is already in progress.")

        return RunRequest(run_config=config, tags=tags)

    return _schedule
