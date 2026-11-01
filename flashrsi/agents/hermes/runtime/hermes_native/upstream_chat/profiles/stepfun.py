"""StepFun provider profile."""

from ..profile_registry import register_provider
from ..provider_base import ProviderProfile

stepfun = ProviderProfile(
    name="stepfun", aliases=("step", "stepfun-coding-plan"), default_aux_model="step-3.5-flash",
    env_vars=("STEPFUN_API_KEY",), base_url="https://api.stepfun.ai/step_plan/v1",
)

register_provider(stepfun)
