from .endBurner import *
from .bates import *
from .finocyl import *
from .moonBurner import *
from .star import *
from .xCore import *
from .cGrain import *
from .dGrain import *
from .rodTube import *
from .conical import *
try:
    from .custom import *  # noqa: F401,F403
except Exception:
    CustomGrain = None

# Generate grain geometry name -> constructor lookup table
grainTypes = {}
grainClasses = [
    BatesGrain,
    EndBurningGrain,
    Finocyl,
    MoonBurner,
    StarGrain,
    XCore,
    CGrain,
    DGrain,
    RodTubeGrain,
    ConicalGrain,
]
if CustomGrain is not None:
    grainClasses.append(CustomGrain)
for grainType in grainClasses:
    grainTypes[grainType.geomName] = grainType
