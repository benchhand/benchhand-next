"""Template for a new family (the leading underscore keeps it out of the registry): copy to
families/<family_id>.py, rename, and replace `run`. See ../README.md."""

from corpus import Family, Pair


def run(mutant: bool) -> str:
    return "fail" if mutant else "pass"


FAMILY = Family(id="example", check="module.path", owner="package", pairs=(Pair("p1", "what is wrong", run),))
