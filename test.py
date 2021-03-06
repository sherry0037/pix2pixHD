### Copyright (C) 2017 NVIDIA Corporation. All rights reserved. 
### Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode).
import os
from collections import OrderedDict
from options.test_options import TestOptions
from data.data_loader import CreateDataLoader
from models.models import create_model
from util.visualizer import Visualizer
from util import html
from metrics import AverageMeter, Result
import torch
import math
import json
import time


opt = TestOptions().parse(save=False)
opt.nThreads = 1   # test code only supports nThreads = 1
opt.batchSize = 1  # test code only supports batchSize = 1
opt.serial_batches = True  # no shuffle
opt.no_flip = True  # no flip

data_loader = CreateDataLoader(opt)
dataset = data_loader.load_data()
dataset_size = len(data_loader)
visualizer = Visualizer(opt)
# create website
web_dir = os.path.join(opt.results_dir, opt.name, '%s_%s' % (opt.phase, opt.which_epoch))
webpage = html.HTML(web_dir, 'Experiment = %s, Phase = %s, Epoch = %s' % (opt.name, opt.phase, opt.which_epoch))

# test
if not opt.engine and not opt.onnx:
    model = create_model(opt)
    if opt.data_type == 16:
        model.half()
    elif opt.data_type == 8:
        model.type(torch.uint8)
            
    if opt.verbose:
        print(model)
else:
    from run_engine import run_trt_engine, run_onnx

errors = dict()
"""total_rmse = 0
total_absrel = 0
total_delta_1 = 0
total_delta_2 = 0
total_delta_3 = 0"""
average_meter = AverageMeter()
end = time.time()
for i, data in enumerate(dataset):
    data_time = time.time() - end
    end = time.time()
    if i >= opt.how_many:
        break
    if opt.data_type == 16:
        data['label'] = data['label'].half()
        data['inst']  = data['inst'].half()
    elif opt.data_type == 8:
        data['label'] = data['label'].uint8()
        data['inst']  = data['inst'].uint8()
    if opt.export_onnx:
        print ("Exporting to ONNX: ", opt.export_onnx)
        assert opt.export_onnx.endswith("onnx"), "Export model file should end with .onnx"
        torch.onnx.export(model, [data['label'], data['inst']],
                          opt.export_onnx, verbose=True)
        exit(0)
    minibatch = 1 
    if opt.engine:
        generated = run_trt_engine(opt.engine, minibatch, [data['label'], data['inst']])
    elif opt.onnx:
        generated = run_onnx(opt.onnx, opt.data_type, minibatch, [data['label'], data['inst']])
    else:        
        generated = model.inference(data['label'], data['inst'], data['image'])

    gpu_time = time.time() - end

    real_image = data['image'][0].cpu()
    fake_image = generated.data[0].cpu()
    source_image = data['label'][0].cpu()

    visuals = OrderedDict(#[('input_label', util.tensor2label(source_image, opt.label_nc)),
                           [('input_label', source_image.numpy()),
                           ('synthesized_image', fake_image.numpy()),
                           ('real_image', real_image.numpy())])
    img_path = data['path']
    print('process image... %s' % img_path)
    visuals = visualizer.visulize_depth(visuals)
    visualizer.save_images(webpage, visuals, img_path)

    # calculate losses
    """valid_mask = real_image > 0
    real_image = real_image[valid_mask]
    fake_image = fake_image[valid_mask]
    abs_diff = (fake_image - real_image).abs()
    mse = float((torch.pow(abs_diff, 2)).mean())
    rmse = math.sqrt(mse)
    absrel = float((abs_diff / real_image).mean())
    maxRatio = torch.max(fake_image/real_image, real_image/fake_image)
    delta1 = float((maxRatio < 1.25).float().mean())
    delta2 = float((maxRatio < 1.25 ** 2).float().mean())
    delta3 = float((maxRatio < 1.25 ** 3).float().mean())
    total_rmse += rmse
    total_absrel += absrel
    total_delta_1 += delta1
    total_delta_2 += delta2
    total_delta_3 += delta3
    errors[i] = {'rmse': rmse, 'absrel': absrel, 'delta1': delta1, 'delta2': delta2, 'delta3': delta3}"""
    result = Result()
    result.evaluate(fake_image, real_image)
    average_meter.update(result, gpu_time, data_time, dataset_size)
    end = time.time()
    errors[i] = result.to_dict()

webpage.save()

"""errors['average'] = {'rmse': total_rmse/dataset_size, 'absrel': total_absrel/dataset_size,
                     'delta1': total_delta_1/dataset_size, 'delta2': total_delta_1/dataset_size, 'delta3': total_delta_1/dataset_size}
"""
avg = average_meter.average()
errors['average'] = avg.to_dict()
errorDict = {'errors': errors}
error_dir = os.path.join(opt.results_dir, 'loss_%s.txt'%opt.name)
with open(error_dir, 'w') as file:
    file.write(json.dumps(errorDict))  # use `json.loads` to do the revers
print("Finish writing at ", error_dir)



