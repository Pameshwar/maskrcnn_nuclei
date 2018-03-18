###########################################
# Library and Path
###########################################

import os
import random
import pickle
import numpy as np
import skimage.io
from skimage.color import gray2rgb, label2rgb
from sklearn.model_selection import train_test_split
import pandas as pd
import time
import glob

from config import Config
import utils
import model as modellib

# Directory of the project and models
ROOT_DIR = os.getcwd()
MODEL_DIR = os.path.join(ROOT_DIR, "logs")
COCO_MODEL_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")
if not os.path.exists(COCO_MODEL_PATH):
    utils.download_trained_weights(COCO_MODEL_PATH)

# Directory of nuclei data
DATA_DIR = os.path.join(ROOT_DIR, "data")
TRAIN_DATA_PATH = os.path.join(DATA_DIR,"stage1_train")
TRAIN_DATA_EXT_PATH = os.path.join(DATA_DIR,"external_processed")
TRAIN_DATA_AUG_PATH = os.path.join(DATA_DIR,"augmented")
TEST_DATA_PATH = os.path.join(DATA_DIR,"stage1_test")
TEST_MASK_SAVE_PATH = os.path.join(DATA_DIR,"stage1_masks_test")

os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import tensorflow as tf
config_tf = tf.ConfigProto()
config_tf.gpu_options.allow_growth = True
session = tf.Session(config=config_tf)
train_flag = True

###########################################
# Training Config
###########################################

# 20180131:
# RPN_ANCHOR_SCALES=(16,32,64,128);
# RPN_TRAIN_ANCHORS_PER_IMAGE=256;
# DETECTION_MAX_INSTANCES=300;
# TRAIN_ROIS_PER_IMAGE=256

class TrainingConfig(Config):

    NAME = "nuclei_train"
    IMAGES_PER_GPU = 2
    GPU_COUNT = 1

    # Number of classes (only nuclei and bg)
    NUM_CLASSES = 1 + 1

    IMAGE_MIN_DIM = 256
    IMAGE_MAX_DIM = 1024

    VALIDATION_STEPS = 136
    STEPS_PER_EPOCH = 1406*2
    MAX_GT_INSTANCES = 400

    RPN_ANCHOR_SCALES = (16, 32, 64, 128)

    RPN_TRAIN_ANCHORS_PER_IMAGE = 256

    DETECTION_MAX_INSTANCES = 300

    TRAIN_ROIS_PER_IMAGE = 256

    RPN_NMS_THRESHOLD = 0.7

    IMAGE_PADDING = True

config = TrainingConfig()
config.display()

###########################################
# Load Nuclei Dataset
###########################################

class NucleiDataset(utils.Dataset):
    def load_image(self, image_id):

        # Load the specified image and return a [H,W,3] Numpy array.
        image = skimage.io.imread(self.image_info[image_id]['path'])
        if image.ndim != 3:
            image = gray2rgb(image)
        elif image.shape[2] == 4:
            image = image[:, :, :3]
        return image

    def load_mask(self, image_id):

        # Load the instance masks (a binary mask per instance)
        # return a a bool array of shape [H, W, instance count]
        mask_dir = os.path.dirname(self.image_info[image_id]['path']).replace('images', 'masks')
        mask_files = next(os.walk(mask_dir))[2]
        num_inst = len(mask_files)

        # get the shape of the image
        mask0 = skimage.io.imread(os.path.join(mask_dir, mask_files[0]))
        class_ids = np.ones(len(mask_files), np.int32)
        mask = np.zeros([mask0.shape[0], mask0.shape[1], num_inst])
        for k in range(num_inst):
            mask[:, :, k] = skimage.io.imread(os.path.join(mask_dir, mask_files[k]))
        return mask, class_ids

###########################################
# TrainVal Split
###########################################

h = open('image_group.pickle')
d = pickle.load(h)
train_ids = []
val_ids = []
for k in range(1,7):
    train_id, val_id = train_test_split(d[k],train_size=0.8, random_state=1234)
    train_ids.extend(train_id)
    val_ids.extend(val_id)

train_ids_aug = []
for train_id in train_ids:
    train_ids_aug.extend(glob.glob(TRAIN_DATA_AUG_PATH+'/'+train_id+'*/images/*.png'))

for k in range(len(train_ids)):
    train_ids[k] = os.path.join(TRAIN_DATA_PATH,train_ids[k],'images',train_ids[k]+'.png')
train_ids_ext = glob.glob(TRAIN_DATA_EXT_PATH+'/*/images/*.png')

train_ids.extend(train_ids_aug)
# train_ids.extend(train_ids_ext)

print(len(train_ids_ext),len(train_ids_aug),len(train_ids))

random.seed(1234)
random.shuffle(train_ids)
random.shuffle(val_ids)

test_ids = next(os.walk(TEST_DATA_PATH))[1]
dataset_train = NucleiDataset()
dataset_train.add_class("cell", 1, "nulcei")
for k, train_id in enumerate(train_ids):
    dataset_train.add_image("cell", k, train_id)
dataset_train.prepare()

dataset_val = NucleiDataset()
dataset_val.add_class("cell", 1, "nulcei")
for k, val_id in enumerate(val_ids):
    dataset_val.add_image("cell", k, os.path.join(TRAIN_DATA_PATH, val_id, 'images', val_id + '.png'))
dataset_val.prepare()

dataset_test = NucleiDataset()
dataset_test.add_class("cell", 1, "nulcei")
for k, test_id in enumerate(test_ids):
    dataset_test.add_image("cell", k, os.path.join(TEST_DATA_PATH, test_id, 'images', test_id + '.png'))
dataset_test.prepare()

###########################################
# Begin Training
###########################################

# Create model object in training mode.
model = modellib.MaskRCNN(mode="training", model_dir=MODEL_DIR, config=config)
init_with = "last"  # imagenet, coco, or last

if init_with == "imagenet":
    model.load_weights(model.get_imagenet_weights(), by_name=True)
elif init_with == "coco":
    # Load weights trained on MS COCO, but skip layers that
    # are different due to the different number of classes
    model.load_weights(COCO_MODEL_PATH, by_name=True,
                       exclude=["mrcnn_class_logits", "mrcnn_bbox_fc", "mrcnn_bbox", "mrcnn_mask"])
elif init_with == "last":
    # Load the last model you trained and continue training
    model.load_weights(model.find_last()[1], by_name=True)

if train_flag:
    # Train the head branches
    # model.train(dataset_train, dataset_val, learning_rate=config.LEARNING_RATE, epochs=20, layers='heads')
    # Fine tune all layers
    model.train(dataset_train, dataset_val, learning_rate=config.LEARNING_RATE/10., epochs=30, layers="all")

###########################################
# Inference Config
###########################################

class InferenceConfig(TrainingConfig):

    # Running inference on one image at a time.
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1

inference_config = InferenceConfig()
model = modellib.MaskRCNN(mode="inference", config=inference_config, model_dir=MODEL_DIR)

# Path to saved weights: either set a specific path or find last trained weights
# model_path = os.path.join(ROOT_DIR, ".h5 file name here")
model_path = model.find_last()[1]
# model_path = '/home/jieyang/code/TOOK18/nuclei_maskrcnn/logs/nuclei_train20180131T1425/mask_rcnn_nuclei_train_0018.h5'
# model_path = '/home/jieyang/code/TOOK18/nuclei_maskrcnn/logs/nuclei_train20180202T1210/mask_rcnn_nuclei_train_0007.h5'
# Load trained weights (fill in path to trained weights here)
assert model_path != "", "Provide path to trained weights"
print("Loading weights from ", model_path)
model.load_weights(model_path, by_name=True)
model_name = model_path.split('/')[-2]
model_epoch = model_path.split('/')[-1].split('.')[0][-5:]
model_name = model_name+model_epoch

###########################################
# Begin Validation
###########################################

TEST_VAL_MASK_SAVE_PATH = '/home/jieyang/code/TOOK18/nuclei_maskrcnn/data/stage1_masks_val/'
if not os.path.exists(TEST_VAL_MASK_SAVE_PATH + '/' + model_name):
    os.makedirs(TEST_VAL_MASK_SAVE_PATH + '/' + model_name)

APs = []
for image_id in dataset_val.image_ids:
    # Load image and ground truth data
    image, image_meta, gt_class_id, gt_bbox, gt_mask = \
        modellib.load_image_gt_noresize(dataset_val, inference_config, image_id, use_mini_mask=False)
    # Run object detection
    t = time.time()
    results = model.detect([image], verbose=0)
    t2 = time.time()
    # print(t2-t)
    r = results[0]
    # Compute AP
    AP = utils.sweep_iou_mask_ap(gt_mask, r["masks"], r["scores"])
    t3 = time.time()
    # print(t3-t2)
    APs.append(AP)
    print np.mean(APs)

    train_id = dataset_val.image_info[image_id]['path'].split('/')[-1][:-4]
    rmaskcollapse_gt = np.zeros((image.shape[0], image.shape[1]))
    for i in range(gt_mask.shape[2]):
        rmaskcollapse_gt = rmaskcollapse_gt + gt_mask[:, :, i] * (i + 1)
    rmaskcollapse_gt = label2rgb(rmaskcollapse_gt, bg_label=0)
    masks = r["masks"]
    rmaskcollapse = np.zeros((image.shape[0], image.shape[1]))
    for i in range(masks.shape[2]):
        rmaskcollapse = rmaskcollapse + masks[:, :, i] * (i + 1)
    rmaskcollapse = label2rgb(rmaskcollapse, bg_label=0)

    skimage.io.imsave(TEST_VAL_MASK_SAVE_PATH + '/' + model_name + '/ap_' + '%.2f' % AP + '_' + train_id + '_mask.png',
                      np.concatenate((rmaskcollapse_gt, image / 255., rmaskcollapse), axis=1))
print("mAP: ", np.mean(APs))

###########################################
# Begin Testing
###########################################

new_test_ids = []
rles = []
if not os.path.exists(TEST_MASK_SAVE_PATH + '/' + model_name):
    os.makedirs(TEST_MASK_SAVE_PATH + '/' + model_name)

for image_id in dataset_test.image_ids:

    results = model.detect([dataset_test.load_image(image_id)], verbose=0)
    r = results[0]
    test_id = dataset_test.image_info[image_id]['path'].split('/')[-1][:-4]

    rmaskcollapse = np.zeros((r['masks'].shape[0], r['masks'].shape[1]))
    for i in range(r['masks'].shape[2]):
        rmaskcollapse = rmaskcollapse + r['masks'][:, :, i] * (i + 1)

    skimage.io.imsave(TEST_MASK_SAVE_PATH + '/' + model_name + '/' + test_id + '_mask.png',
                      np.concatenate((dataset_test.load_image(image_id) / 255.,
                                      label2rgb(rmaskcollapse, bg_label=0)), axis=1))

    for i in range(r['masks'].shape[2]):
        rle = list(utils.prob_to_rles(r['masks'][:, :, i]))
        rles.extend(rle)
        new_test_ids.append(test_id)

# Create submission DataFrame
sub = pd.DataFrame()
sub['ImageId'] = new_test_ids
sub['EncodedPixels'] = pd.Series(rles).apply(lambda x: ' '.join(str(y) for y in x))
sub.to_csv('submission/sub-test-'+model_name+'.csv', index=False)
