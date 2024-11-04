import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import wandb
from yaml import safe_load as yaml_safe_load
from model import create_model

dataset_metadata = yaml_safe_load(open("dataset/metadata.yaml", "r"))


class ImageClassifier(pl.LightningModule):
    def __init__(self, config):
        super().__init__()
        self.config = config  # global configuration
        self.dataset_metadata = dataset_metadata[config["dataset"]]
        self.save_hyperparameters()

        # note: when the config num_classes is less than the total number of classes
        # in the dataset, we exclude some classes from train, eval and test data.
        # Here we pass the total number of classes to the model: we have more output
        # units than number of classes; then model needs to learn that some of the
        # classes never come up.
        model_config = config["model"]["config"]
        model_config["num_classes"] = self.dataset_metadata["num_classes"]
        model_config["in_channels"] = self.dataset_metadata["num_channels"]
        model_config["input_size"] = (
            self.dataset_metadata["height"]
            * self.dataset_metadata["width"]
            * self.dataset_metadata["num_channels"]
        )
        self.model = create_model(
            config["model"]["architecture"],
            config=model_config,
        )

    def forward(self, x):
        return self.model(x)

    def training_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.cross_entropy(logits, y)

        acc = (logits.argmax(dim=1) == y).float().mean()
        self.log("train/loss", loss, on_step=True, on_epoch=True)
        self.log("train/acc", acc, on_step=True, on_epoch=True)

        if (batch_idx + 1) % self.config["logging"]["image_log_freq"] == 0:
            self._log_images(x, y, logits, "train")

        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.cross_entropy(logits, y)

        acc = (logits.argmax(dim=1) == y).float().mean()
        self.log("val/loss", loss, on_epoch=True)
        self.log("val/acc", acc, on_epoch=True)

        if batch_idx == 0:  # Log images from first validation batch
            self._log_images(x, y, logits, "val")

        return loss

    def test_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.cross_entropy(logits, y)

        # Log metrics
        acc = (logits.argmax(dim=1) == y).float().mean()
        self.log("test/loss", loss, on_epoch=True)
        self.log("test/acc", acc, on_epoch=True)

        return loss

    def _log_images(self, x, y, logits, prefix, num_images=8):
        if not self.config["logging"]["wandb_logging"]:
            return
        preds = logits.argmax(dim=1)

        if "class_names" in self.dataset_metadata:
            true_labels = [
                self.dataset_metadata["class_names"][y[i].item()]
                for i in range(min(num_images, len(x)))
            ]
            pred_labels = [
                self.dataset_metadata["class_names"][preds[i].item()]
                for i in range(min(num_images, len(x)))
            ]
        else:
            true_labels = [y[i].item() for i in range(min(num_images, len(x)))]
            pred_labels = [preds[i].item() for i in range(min(num_images, len(x)))]

        images = [
            wandb.Image(x[i], caption=f"True: {true_labels[i]}\nPred: {pred_labels[i]}")
            for i in range(min(num_images, len(x)))
        ]

        self.logger.experiment.log({f"{prefix}-images": images})

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.config["training"]["learning_rate"],
            weight_decay=self.config["training"]["weight_decay"],
        )
        return optimizer
