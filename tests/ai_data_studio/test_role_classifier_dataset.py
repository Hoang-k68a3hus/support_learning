from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from ai_data_studio.training.role_classifier import (
    RoleClassifierDatasetError,
    RoleClassifierDatasetSplit,
    RoleClassifierLabelSource,
    RoleClassifierTeacher,
    RoleClassifierTrainingDataset,
    RoleClassifierTrainingExample,
    RoleClassifierTrainingTarget,
    load_role_classifier_training_dataset,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticTextView,
)
from source_understanding.semantics import (
    SemanticRequest,
    SemanticRequestSegment,
    SemanticTargetKind,
)


CONTENT_HASH = "sha256:" + "a" * 64
TEACHER_HASH = "sha256:" + "b" * 64


def logical_request(index: int = 0) -> SemanticRequest:
    text = f"Gradient descent definition {index}."
    element_id = f"e{index}"
    return SemanticRequest(
        target_id=f"lu{index}",
        target_kind=SemanticTargetKind.LOGICAL_UNIT,
        text=text,
        language="en",
        element_ids=(element_id,),
        target_segments=(
            SemanticRequestSegment(
                element_id=element_id,
                text=text,
                text_view=SemanticTextView.RAW_TEXT,
                element_start=0,
                element_end=len(text),
                request_start=0,
                request_end=len(text),
            ),
        ),
        logical_unit_type="TEXT_BLOCK",
        context_labels=("Optimization",),
    )


def training_example(
    *,
    example_id: str,
    split: RoleClassifierDatasetSplit,
    label_source: RoleClassifierLabelSource,
    document_id: str | None = None,
    content_hash: str = CONTENT_HASH,
    source_family_id: str | None = None,
    split_group_id: str | None = None,
    target_order: int = 0,
    teacher: RoleClassifierTeacher | None = None,
) -> RoleClassifierTrainingExample:
    request_index = int(example_id.removeprefix("ex"))
    request = logical_request(request_index)
    return RoleClassifierTrainingExample(
        example_id=example_id,
        document_id=document_id or f"doc-{example_id}",
        content_hash=content_hash,
        source_family_id=source_family_id or f"family-{example_id}",
        split_group_id=split_group_id or f"group-{example_id}",
        target=RoleClassifierTrainingTarget(
            target_id=request.target_id,
            element_ids=request.element_ids,
            element_orders=(target_order,),
        ),
        request=request,
        labels=(SemanticAnnotationType.DEFINITION,),
        split=split,
        label_source=label_source,
        teacher=teacher,
    )


class RoleClassifierDatasetTests(unittest.TestCase):
    def test_supports_negative_and_reproducible_silver_rows(self) -> None:
        silver = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.LLM_SILVER,
            teacher=RoleClassifierTeacher(
                provider_name="teacher",
                provider_version="1",
                configuration_hash=TEACHER_HASH,
            ),
        ).model_copy(update={"labels": ()})
        dataset = RoleClassifierTrainingDataset(
            name="role-training",
            dataset_version="1",
            examples=(silver,),
        )

        self.assertEqual(dataset.examples[0].labels, ())
        teacher = dataset.examples[0].teacher
        self.assertIsNotNone(teacher)
        if teacher is not None:
            self.assertEqual(teacher.configuration_hash, TEACHER_HASH)

    def test_test_split_rejects_silver_labels(self) -> None:
        with self.assertRaisesRegex(ValidationError, "TEST examples must be human-only"):
            training_example(
                example_id="ex0",
                split=RoleClassifierDatasetSplit.TEST,
                label_source=RoleClassifierLabelSource.LLM_SILVER,
                teacher=RoleClassifierTeacher(
                    provider_name="teacher",
                    provider_version="1",
                    configuration_hash=TEACHER_HASH,
                ),
            )

    def test_request_target_id_must_match_source_stable_target(self) -> None:
        valid = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )
        mismatched = valid.target.model_copy(update={"target_id": "different-lu"})
        with self.assertRaisesRegex(ValidationError, "target_id must match"):
            RoleClassifierTrainingExample.model_validate(
                {**valid.model_dump(mode="python"), "target": mismatched}
            )

    def test_request_element_ids_must_match_source_stable_target(self) -> None:
        valid = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )
        mismatched = valid.target.model_copy(update={"element_ids": ("other",)})
        with self.assertRaisesRegex(ValidationError, "element_ids must exactly match"):
            RoleClassifierTrainingExample.model_validate(
                {**valid.model_dump(mode="python"), "target": mismatched}
            )

    def test_rejects_same_source_target_across_splits(self) -> None:
        train = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )
        test = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TEST,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )
        with self.assertRaisesRegex(ValidationError, "occurs more than once"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="1",
                examples=(train, test),
            )

    def test_rejects_duplicate_source_target_inside_one_split(self) -> None:
        first = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )
        duplicate = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
        )

        with self.assertRaisesRegex(ValidationError, "occurs more than once"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(first, duplicate),
            )

    def test_same_split_group_cannot_cross_splits(self) -> None:
        train = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "c" * 64,
            split_group_id="shared-group",
        )
        test = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TEST,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "d" * 64,
            split_group_id="shared-group",
        )

        with self.assertRaisesRegex(ValidationError, "split_group_id leaks"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(train, test),
            )

    def test_same_source_family_cannot_cross_splits(self) -> None:
        train = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "c" * 64,
            source_family_id="shared-family",
        )
        test = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TEST,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "d" * 64,
            source_family_id="shared-family",
        )

        with self.assertRaisesRegex(ValidationError, "source_family_id leaks"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(train, test),
            )

    def test_same_source_family_cannot_cross_groups_inside_one_split(self) -> None:
        first = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "c" * 64,
            source_family_id="shared-family",
            split_group_id="group-a",
        )
        second = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            content_hash="sha256:" + "d" * 64,
            source_family_id="shared-family",
            split_group_id="group-b",
        )

        with self.assertRaisesRegex(ValidationError, "crosses split groups"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(first, second),
            )

    def test_same_content_hash_cannot_cross_splits_for_different_targets(self) -> None:
        train = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            target_order=0,
        )
        test = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TEST,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            target_order=1,
        )

        with self.assertRaisesRegex(ValidationError, "content_hash leaks"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(train, test),
            )

    def test_same_content_hash_cannot_cross_groups_inside_one_split(self) -> None:
        first = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            split_group_id="group-a",
            target_order=0,
        )
        second = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            split_group_id="group-b",
            target_order=1,
        )

        with self.assertRaisesRegex(ValidationError, "crosses split groups"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(first, second),
            )

    def test_same_document_id_cannot_cross_splits(self) -> None:
        train = training_example(
            example_id="ex0",
            split=RoleClassifierDatasetSplit.TRAIN,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            document_id="shared-document",
            content_hash="sha256:" + "c" * 64,
            source_family_id="family-a",
            split_group_id="group-a",
        )
        test = training_example(
            example_id="ex1",
            split=RoleClassifierDatasetSplit.TEST,
            label_source=RoleClassifierLabelSource.HUMAN_GOLD,
            document_id="shared-document",
            content_hash="sha256:" + "d" * 64,
            source_family_id="family-b",
            split_group_id="group-b",
        )

        with self.assertRaisesRegex(ValidationError, "document_id leaks"):
            RoleClassifierTrainingDataset(
                name="role-training",
                dataset_version="2",
                examples=(train, test),
            )

    def test_loader_wraps_invalid_dataset_with_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text(json.dumps({"name": "missing examples"}), encoding="utf-8")

            with self.assertRaisesRegex(
                RoleClassifierDatasetError, "invalid role classifier dataset"
            ):
                load_role_classifier_training_dataset(path)


if __name__ == "__main__":
    unittest.main()
