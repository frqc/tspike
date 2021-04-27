import click
import torch
import numpy as np
from torch.utils.data.dataloader import DataLoader
from tqdm import tqdm

from dataset import NMnistSampled
from tnn import AutoMatchingMatrix, FullDualColumn
from sklearn.metrics import accuracy_score


class Interrupter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            return True
        return exc_type is None


@click.command()
@click.option('-g', '--gpu', default=0)
@click.option('-e', '--epochs', default=1)
@click.option('-i', '--bias', default=0.5)  # new
@click.option('-k', '--decay', default=0.99)
@click.option('-b', '--batch', default=32)
@click.option('-x', '--x-max', default=34)
@click.option('-y', '--y-max', default=34)
@click.option('-t', '--t-max', default=256)
@click.option('-r', '--winners', default=1)
@click.option('-n', '--neurons', default=1)
@click.option('-f', '--forced-dep', default=0)
@click.option('-d', '--dense', default=0.1)  # new
@click.option('-s', '--step', default=16)
@click.option('-l', '--leak', default=32)
@click.option('-w', '--w-init', default=0.5)
@click.option('--capture', default=0.20)
@click.option('--backoff', default=-0.20)
@click.option('--search', default=0.01)
@click.option('-S/-U', '--supervised/--unsupervised', default=True)
@click.option('--train-path', default='data/n-mnist/TrainSP')
@click.option('--test-path', default='data/n-mnist/TestSP')
@click.option('--model-path', default='model/n-mnist-du')
def main(
    gpu, batch, epochs, supervised,
    x_max, y_max, t_max, neurons, winners,
    step, leak,
    forced_dep, dense, w_init, bias,
    capture, backoff, search, decay,
    train_path, test_path, model_path,
    **kwargs
):
    if torch.cuda.is_available():
        dev = f'cuda:{gpu}'
    else:
        dev = 'cpu'
    device = torch.device(dev)

    print(f'Device: {device}, Batch: {batch}, Supervised: {supervised}')
    print(f'Forced Dep: {forced_dep}, Dense: {dense}')
    print(f'Capture: {capture}, Backoff: {backoff}, Search: {search}')

    train_data_loader = DataLoader(NMnistSampled(
        train_path, x_max, y_max, t_max, device=device), shuffle=True, batch_size=batch)
    test_data_loader = DataLoader(NMnistSampled(
        test_path, x_max, y_max, t_max, device=device), batch_size=batch)

    model = FullDualColumn(
        x_max * y_max, neurons, input_channel=2, output_channel=10, winners=winners,
        step=step, leak=leak, bias=bias,
        dense=dense, fodep=forced_dep, w_init=w_init
    ).to(device)

    def descriptor():
        max_print = 10
        s = f"{','.join(f'{x*100:.0f}' for x in model.weight.mean(axis=1)[:max_print])}; "
        s += f"{','.join(f'{x*100:.0f}' for x in model.bias[:max_print])}; "

        return s

    for epoch in range(epochs):
        model.train(mode=True)
        print(f"epoch: {epoch}")
        train_data_iterator = tqdm(train_data_loader)
        train_data_iterator.set_description(descriptor())
        with Interrupter():
            for data, label in train_data_iterator:
                input_spikes = data.reshape(-1, 2, x_max * y_max, t_max)
                if supervised:
                    output_spikes = model.forward(
                        input_spikes, label.to(device), mu_capture=capture, mu_backoff=backoff, mu_search=search, beta_decay=decay)
                else:
                    output_spikes = model.forward(input_spikes, bias=0.5)
                # output_spikes: bacth, channel, neuro, time
                accurate = (output_spikes.sum((-3, -2, -1)) > 0).logical_and(
                    output_spikes.sum((-2, -1)).argmax(-1) == label.to(device)).sum()
                train_data_iterator.set_description(
                    f'{descriptor()}; {output_spikes.sum()}, {accurate}')

        model.train(mode=False)
        auto_matcher = AutoMatchingMatrix(10, 10)

        real_labels = []
        predicted_labels = []
        with Interrupter():
            for data, label in tqdm(test_data_loader):
                input_spikes = data.reshape(-1, 2, x_max * y_max, t_max)
                output_spikes = model.forward(input_spikes)

                has_spikes = output_spikes.sum((-3, -2, -1)) > 0
                y_preds = output_spikes.sum((-2, -1)).argmax(-1)

                for has_spike, y_pred, y_true in zip(has_spikes.cpu().numpy(), y_preds.cpu().numpy(), label.numpy()):
                    if has_spike:
                        auto_matcher.add_sample(y_true, y_pred)

                    predicted_labels.append(y_pred)
                    real_labels.append(y_true)

        with Interrupter():
            print(auto_matcher.mat)
            if np.all(np.sum(auto_matcher.mat, axis=0)) and np.all(np.sum(auto_matcher.mat, axis=1)):
                accuracy, precision, recall = auto_matcher.describe()
                print(accuracy, precision, recall)
            else:
                accuracy, precision, recall = -1, -1, -1

            accuracy = accuracy_score(real_labels, predicted_labels)
            torch.save(model.state_dict(), model_path)

            print(accuracy, precision, recall)

    return 0


if __name__ == '__main__':
    exit(main())
