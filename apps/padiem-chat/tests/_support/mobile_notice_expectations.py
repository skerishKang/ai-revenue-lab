"""Authored values expected by the mobile notice layout contract (#8056).

Kept out of the test module so the contract asserts parsed structure and user
copy rather than repeating raw source literals (see #8060 rule).
"""

POSITION = "position"
FIXED = "fixed"
STATIC = "static"
RIGHT = "right"
TOP = "top"
TWENTY_PX = "20px"
MARGIN = "margin"
TWELVE_PX = "12px"
MAX_WIDTH = "max-width"
NONE = "none"
HIDDEN = "hidden"
ROLE_STATUS = 'role="status"'
ARIA_LIVE = 'aria-live="polite"'
HIDDEN_RULE = ".feedback-notice[hidden] { display: none !important; }"
