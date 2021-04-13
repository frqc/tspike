from tnn.configs import MAX_WEIGHT
import click
import torch
from torch.utils.data.dataloader import DataLoader
from tqdm import tqdm

from dataset import NMnistSampled
from tnn import AutoMatchingMatrix, FullColumn, set_device


@click.command()
@click.option('-g', '--gpu', default=0)
@click.option('-e', '--epochs', default=10)
@click.option('-b', '--batch', default=1)
@click.option('-x', '--x-max', default=34)
@click.option('-y', '--y-max', default=34)
@click.option('-t', '--t-max', default=256)
@click.option('--train-path', default='data/n-mnist/TrainSP')
@click.option('--test-path', default='data/n-mnist/TestSP')
@click.option('--model-path', default='model/n-mnist-1')
def main(
    gpu, batch, epochs,
    x_max, y_max, t_max,
    train_path, test_path, model_path,
    **kwargs
):
    if torch.cuda.is_available():  
        dev = f'cuda:{gpu}' 
    else:  
        dev = 'cpu'
    device = torch.device(dev)
    set_device(device)
    
    
    train_data_loader = DataLoader(NMnistSampled(train_path, x_max, y_max, t_max), shuffle=True, batch_size=batch)
    test_data_loader = DataLoader(NMnistSampled(test_path, x_max, y_max, t_max), batch_size=batch)

    model = FullColumn(x_max * y_max, 10, input_channel=2, output_channel=1, dense=20, fodep=t_max)
    

    for epoch in range(epochs):
        print(f"epoch: {epoch}")
        train_data_iterator = tqdm(train_data_loader)
        train_data_iterator.set_description(f'weight: {model.weight.sum()}')
        for i, sample in enumerate(train_data_iterator):
            input_spikes = sample['data'].reshape(batch, 2, x_max * y_max, t_max).to(device)
            output_spikes = model.forward(input_spikes, sample['label'])
            model.stdp(input_spikes, output_spikes)
            train_data_iterator.set_description(f'weight: {model.weight.sum()}')
        
        auto_matcher = AutoMatchingMatrix(10, 10)
        for sample in tqdm(test_data_loader):
            input_spikes = sample['data'].reshape(batch, 2, x_max * y_max, t_max).to(device)
            output_spikes = model.forward(input_spikes)
            for output_spike, label in zip(output_spikes, sample['label']):
                prediction = output_spike.sum(axis=(-1, -3)).argmax()
                auto_matcher.add_sample(label, prediction)
        
        print(auto_matcher.mat)
        auto_matcher.describe_print_clear()
        print(f'weight sum: {model.weight.sum()}')
        torch.save(model.state_dict, model_path)

    return 0

if __name__ == '__main__':
    exit(main())
