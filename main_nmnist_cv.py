import click
import torch
from torch.utils.data.dataloader import DataLoader
from tqdm import tqdm

from dataset import NMnistSampled
from tnn import AutoMatchingMatrix, ConvColumn


class Interrupter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            return True
        return exc_type is None


class LinearModel(torch.nn.Module):
    def __init__(self, input_size, output_size):
        super(LinearModel, self).__init__()
        self.layer = torch.nn.Linear(input_size, output_size)
    
    def forward(self, input_data):
        output = self.layer(input_data)
        logits = torch.log_softmax(output, dim=1)
        return logits


@click.command()
@click.option('-g', '--gpu', default=0)
@click.option('-e', '--epochs', default=1)
@click.option('-b', '--batch', default=32)
@click.option('-x', '--x-max', default=34)
@click.option('-y', '--y-max', default=34)
@click.option('-t', '--t-max', default=256)
@click.option('-f', '--forced-dep', default=0)
@click.option('-d', '--dense', default=0.30)
@click.option('-w', '--w-init', default=0.5)
@click.option('-s', '--step', default=16)
@click.option('-l', '--leak', default=32)
@click.option('-c', '--channel', default=8)
@click.option('--capture', default=0.2000)
@click.option('--backoff', default=-0.2000)
@click.option('--search', default=0.0001)
@click.option('-S/-U', '--supervised/--unsupervised', default=True)
@click.option('--train-path', default='data/n-mnist/TrainSP')
@click.option('--test-path', default='data/n-mnist/TestSP')
@click.option('--model-path', default='model/n-mnist-cv')
def main(
    gpu, batch, epochs, supervised,
    x_max, y_max, t_max, 
    step, leak,
    forced_dep, dense, w_init, channel,
    capture, backoff, search,
    train_path, test_path, model_path,
    **kwargs
):
    if torch.cuda.is_available():  
        dev = f'cuda:{gpu}' 
    else:  
        dev = 'cpu'
    device = torch.device(dev)

    print(f'Device: {device}, Batch: {batch}, Epochs: {epochs}, Supervised: {supervised}')
    print(f'Forced Dep: {forced_dep}, Dense: {dense}, Weight Init: {w_init}')

    train_data_loader = DataLoader(NMnistSampled(train_path, x_max, y_max, t_max, device=device), shuffle=True, batch_size=batch)
    test_data_loader = DataLoader(NMnistSampled(test_path, x_max, y_max, t_max, device=device), batch_size=batch)

    model = ConvColumn(
        input_channel=2, output_channel=channel, 
        kernel=3, stride=2,
        step=step, leak=leak,
        dense=dense, fodep=forced_dep, w_init=w_init
    ).to(device)
    
    def descriptor():
        return ','.join('{:.0f}'.format(x) for x in model.weight.sum((1, 2, 3)).detach())
    
    def othogonal():
        oc, ic, x, y = model.weight.shape
        w = model.weight.reshape(oc, -1)
        w = w / (w ** 2).sum(1, keepdim=True).sqrt()
        return (((w @ w.T) ** 2).mean() - 1 / oc).sqrt()

    for epoch in range(epochs):
        print(f"epoch: {epoch}")

        model.train(mode=True)
        train_data_iterator = tqdm(train_data_loader)
        with Interrupter():
            for data, label in train_data_iterator:
                input_spikes = data
                output_spikes = model.forward(input_spikes, mu_capture=capture, mu_backoff=backoff, mu_search=search)
                train_data_iterator.set_description(
                    f'weight sum:{descriptor()}; ' 
                    f'weight othogonal:{othogonal():.4f}; '
                    f'total spikes:{output_spikes.sum().int()}; '
                    f'time coverage:{(output_spikes.sum((1, 2, 3)) > 0).float().mean() * 100:.2f}')
        
        model.train(mode=False)
        torch.save(model.state_dict(), model_path)

        train_data_iterator = tqdm(train_data_loader)
        batch, channel, neuron_x, neuron_y, time = output_spikes.shape
        tester = LinearModel(channel * neuron_x * neuron_y, 10).to(device)
        tester.train()
        optimizer = torch.optim.Adam(model.parameters())
        error = torch.nn.CrossEntropyLoss()
        with Interrupter():
            for data, label in train_data_iterator:
                input_spikes = data
                output_spikes = model.forward(input_spikes)
                optimizer.zero_grad()
                output = tester.forward(output_spikes.sum(-1).reshape(-1, channel * neuron_x * neuron_y))
                loss = error(output, label.to(device))
                train_data_iterator.set_description(f'loss={loss.detach().cpu().numpy():.4f}')
                loss.backward()
                optimizer.step()

        auto_matcher = AutoMatchingMatrix(10, 10)
        test_data_iterator = tqdm(test_data_loader)
        with Interrupter():
            for data, label in test_data_iterator:
                input_spikes = data
                output_spikes = model.forward(input_spikes)
                output = tester.forward(output_spikes.sum(-1).reshape(-1, channel * neuron_x * neuron_y)).argmax(-1).cpu()
                for y_pred, y_true in zip(output, label):
                    auto_matcher.add_sample(y_true, y_pred)
        
        print(auto_matcher.mat)
        with Interrupter():
            auto_matcher.describe_print_clear()

    return 0

if __name__ == '__main__':
    exit(main())
