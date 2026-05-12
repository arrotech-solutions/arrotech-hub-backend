class SkillError(Exception):
    pass

class SkillLoadError(SkillError):
    pass

class SkillValidationError(SkillError):
    pass

class SkillNotFoundError(SkillError):
    pass
