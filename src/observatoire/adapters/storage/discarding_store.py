"""An AnnotationStore that keeps nothing: the fake annotator's dry runs.

The fake answers "no statement" for every passage. Stored, those answers would count as
an annotator covering every passage, and could empty the register. A dry run shows what
an annotation run would do, and writes nothing.
"""

from observatoire.domain.annotation import SegmentAnnotation


class DiscardingAnnotationStore:
    def annotated_segments(self, annotator_version: str) -> dict[str, str]:
        return {}

    def save_annotation(self, annotation: SegmentAnnotation) -> None:
        return None
