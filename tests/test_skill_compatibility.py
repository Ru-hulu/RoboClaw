from roboclaw.embodied.capabilities import infer_capabilities, resolve_available_skills
from roboclaw.embodied.definition.components.robots.model import PrimitiveSpec, quick_manifest
from roboclaw.embodied.definition.foundation.schema import CapabilityFamily, CommandMode, PrimitiveKind, RobotType
from roboclaw.embodied.execution.orchestration.skills import SkillSpec


def _profile():
    manifest = quick_manifest(
        id="demo",
        name="Demo",
        robot_type=RobotType.ARM,
        primitives=(
            PrimitiveSpec("joint_move", PrimitiveKind.MOTION, CapabilityFamily.JOINT_MOTION, CommandMode.POSITION, "Move joints."),
            PrimitiveSpec("gripper_open", PrimitiveKind.END_EFFECTOR, CapabilityFamily.END_EFFECTOR, CommandMode.DISCRETE_TRIGGER, "Open gripper."),
        ),
    )
    return infer_capabilities(manifest)


def test_resolve_available_skills_filters_by_capabilities() -> None:
    available = SkillSpec("pick", "Pick.", (), required_capabilities=(CapabilityFamily.END_EFFECTOR,))
    missing = SkillSpec("inspect", "Inspect.", (), required_capabilities=(CapabilityFamily.CAMERA,))

    resolved = resolve_available_skills(_profile(), (available, missing))

    assert resolved == (available,)


def test_resolve_available_skills_excludes_unmet_skill() -> None:
    skill = SkillSpec("inspect", "Inspect.", (), required_capabilities=(CapabilityFamily.CAMERA,))

    assert resolve_available_skills(_profile(), (skill,)) == ()
