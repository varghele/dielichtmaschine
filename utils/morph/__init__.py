# utils/morph/ - show morphing (v1.5b, docs/design-show-morphing.md).
#
# The morph is a COMPILE STEP, never a runtime layer: plan.py holds the
# user-authored patch plan (*.morphplan.yaml), compile.py turns
# (config A, setlist, plan, config B) into ordinary shows inside config
# B. No consumer of show data knows morphing exists.
