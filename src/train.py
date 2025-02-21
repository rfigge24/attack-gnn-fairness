import csv
import random
import time
import argparse
import numpy as np
# import scipy.sparse as sp
from random import choice
import torch
import torch.nn.functional as F
import torch.optim as optim
import dgl
from attack.attack import attack

from utils import *

parser = argparse.ArgumentParser()
parser.add_argument('--no-cuda', action='store_true', default=False,
                    help='Disables CUDA training.')
'''
            Dataset args
'''
parser.add_argument('--dataset', type=str, default='dblp',
                    choices=['pokec_z', 'pokec_n', 'dblp'])
parser.add_argument('--train_percent_atk', type=float, default=0.5,
                    help='Percentage of labeled data available to the attacker.')
parser.add_argument('--train_percent_gnn', type=float, default=0.5,
                    help='Percentage of labeled data as train set.')
parser.add_argument('--val_percent', type=float, default=0.25,
                    help='Percentage of labeled data as validation set.')
'''
            Model args
'''
parser.add_argument('--model', type=str, default=['gcn'], nargs='+',
                    choices=['gcn', 'gat', 'gsage', 'fairgnn'])
parser.add_argument('--lr', type=float, default=0.001,
                    help='Initial learning rate.')
parser.add_argument('--weight_decay', type=float, default=5e-4,
                    help='Weight decay (L2 loss on parameters).')
parser.add_argument('--hidden', type=int, default=64,
                    help='Number of hidden units.')
parser.add_argument('--dropout', type=float, default=0.6,
                    help='Dropout rate (1 - keep probability).')
parser.add_argument('--attack_type', type=str, default='fair_attack',
                    choices=['none', 'random', 'dice', 'fair_attack'],
                    help='Adversarial attack type.')
parser.add_argument('--sensitive', type=str, default='region',
                    choices=['gender', 'region'],
                    help='Sensitive attribute of Pokec.')
parser.add_argument("--preprocess_pokec", type=bool, default=False,
                    help="Include only completed accounts in Pokec datasets (only valid when dataset==pokec_n/pokec_z])")
parser.add_argument('--ptb_rate', type=float, nargs='+', default=[0.05],
                    help="Attack perturbation rate [0-1]")
parser.add_argument("--num_layers", type=int, default=2,
                    help="number of hidden layers")
# ----args for FairAttack
parser.add_argument('--direction', type=str, default='y1s1',
                    choices=['y1s1', 'y1s0', 'y0s0', 'y0s1'],
                    help='FairAttack direction')
parser.add_argument('--strategy', type=str, default='DD',
                    choices=['DD', 'DE', 'ED', 'EE'],
                    help='FairAttack strategy indicating [D]ifferent/[E]qual label(y)|sens(s)')
parser.add_argument('--deg', type=int, default=0,  # may not finish on small datasets
                    choices=[0, 1, 2, 3],
                    help='Degree parameter, 0 for not considering degree, '
                         'd(high)>deg*d(low).')
parser.add_argument('--deg_direction', type=str, default='null',
                    choices=['hl', 'lh', 'null'],
                    help='Direction of degree difference, '
                         'hl for (subject-influencer)=(high-low), and vice versa,'
                         'null for not considering degree.')

# ----args for GSAGE
parser.add_argument('--agg_type', type=str, default='mean',
                    choices=['gcn', 'mean', 'pool', 'lstm'],
                    help='Aggregator for GraphSAGE')

# ----args for GAT
parser.add_argument("--num_heads", type=int, default=8,
                    help="number of hidden attention heads")
parser.add_argument("--num_out_heads", type=int, default=1,
                    help="number of output attention heads")
parser.add_argument("--in_drop", type=float, default=.6,
                    help="input feature dropout")
parser.add_argument("--attn_drop", type=float, default=.6,
                    help="attention dropout")
parser.add_argument('--negative_slope', type=float, default=0.2,
                    help="the negative slope of leaky relu")
parser.add_argument("--residual", action="store_true", default=False,
                    help="use residual connection")

# ----args for fairgnn
parser.add_argument('--base_model', type=str, default='GCN',
                    choices=['GCN', 'GAT'],
                    help='Base GNN model for FairGNN')
parser.add_argument('--alpha', type=float, default=2,
                    help='The hyperparameter of alpha')
parser.add_argument('--beta', type=float, default=0.1,
                    help='The hyperparameter of beta')
parser.add_argument('--sens_number', type=int, default=200,
                    help="the number of sensitive attributes")

'''
            Optimization args
'''
parser.add_argument('--epochs', type=int, default=500,
                    help='Number of epochs to train.')
parser.add_argument('--fastmode', action='store_true', default=False,
                    help='Validate during training pass.')
parser.add_argument(
    '--acc',
    type=float,
    default=0.2,
    help='the selected FairGNN accuracy on val would be at least this high')
parser.add_argument(
    '--roc',
    type=float,
    default=0.5,
    help='the selected FairGNN ROC score on val would be at least this high')

args = parser.parse_known_args()[0]
args.cuda = not args.no_cuda and torch.cuda.is_available()
device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
# seed_set = [42, 10, 1, 2, 100] # for german the seed 0 will have all predictions=1 for surrogate model
seed_set = [42, 0, 1, 2, 100]  # for datasets except german
# seed_set = [0]

# %%
for model_name in args.model:
    for ptb_rate in args.ptb_rate:
        FINAL_RESULT = []
        N = len(seed_set)
        for repeat in range(N):
            seed = seed_set[repeat]
            np.random.seed(seed)
            torch.manual_seed(seed)
            if args.cuda:
                torch.cuda.manual_seed(seed)

            # Load data
            print(args.dataset)
            adj, features, labels, idx_train_atk, idx_train_gnn, idx_val, idx_test, sens, idx_sens_train, dataset, sens_attr, sens_number = \
                load_dataset(args, seed)

            if args.attack_type != 'none':
                adj = attack(args, ptb_rate, adj, features, labels, sens, idx_train_atk, idx_val, idx_test,
                             seed, dataset, sens_attr, idx_sens_train)
                #############################
                # SAving attacked graph code here
                G = dgl.from_scipy(adj)
                dgl.save_graphs(f'../data/{args.dataset}_attacked_{repeat}.bin', G)
                #############################

                print("edge dist. after attack:")
                check_dataset(dataset, adj, labels, sens, idx_train_gnn, idx_val, idx_test)

            print("Test samples:", len(idx_test))
            if sens_attr:
                sens[sens > 0] = 1
            idx_train = idx_train_gnn
            # from torch_geometric.utils import dropout_adj, convert
            # edge_index = convert.from_scipy_sparse_matrix(adj)[0]
            G = dgl.from_scipy(adj)
            if args.cuda:
                G = G.to(device)
            # Model and optimizer
            if model_name == 'gcn':  # two layer GCN
                from models.GCN import GCN

                model = GCN(G,
                            features.shape[1],  #
                            args.hidden,
                            1,
                            args.num_layers,
                            F.relu,
                            args.dropout)
            elif model_name == 'gsage':
                from models.GraphSAGE import GraphSAGE

                model = GraphSAGE(G,
                                  features.shape[1],
                                  args.hidden,
                                  1,
                                  args.num_layers,
                                  F.relu,
                                  args.dropout,
                                  args.agg_type)
            elif model_name == 'gat':
                from models.GAT import GAT

                heads = ([args.num_heads] * args.num_layers) + [args.num_out_heads]
                model = GAT(G,
                            1,  # num_layers
                            features.shape[1],
                            args.hidden,
                            1,
                            heads,
                            args.in_drop,
                            args.attn_drop,
                            args.negative_slope,
                            args.residual)

            elif model_name == 'fairgnn':
                from models.FairGNN import FairGNN

                model = FairGNN(G, nfeat=features.shape[1], args=args)
                model.estimator.load_state_dict(torch.load(
                    "./checkpoint/GCN_sens_{}_ns_{}".format(args.dataset, sens_number), map_location=device.type))

            if args.cuda:
                model.cuda()
                features = features.cuda()
                # adj = adj.cuda()
                sens = sens.cuda()
                labels = labels.cuda()
                idx_train = idx_train.cuda()
                idx_val = idx_val.cuda()
                idx_test = idx_test.cuda()
                idx_sens_train = idx_sens_train.cuda()

            optimizer = optim.Adam(model.parameters(),
                                   lr=args.lr, weight_decay=args.weight_decay)
            loss_fcn = torch.nn.BCEWithLogitsLoss()
            # Train model
            t_total = time.time()
            vali_max = [0, [0, 0, 0, 0, 0, 0], [100, 100, 100], -1]
            loss_all = []
            for epoch in range(args.epochs + 1):
                if model_name == 'fairgnn':
                    # train fairgnn
                    model.train()
                    model.optimize(G, features, labels, idx_train, sens, idx_sens_train)
                    cov = model.cov
                    cls_loss = model.cls_loss
                    adv_loss = model.adv_loss
                    model.eval()
                    output, s = model(features)
                    acc_train, roc_train, _, _, _, _ = classification_metrics(
                        output[idx_train], labels[idx_train])
                else:
                    model.train()
                    optimizer.zero_grad()
                    output = model(features)
                    loss_train = loss_fcn(
                        output[idx_train],
                        labels[idx_train].unsqueeze(1).float())
                    loss_all.append(loss_train.detach().cpu().item())
                    acc_train, roc_train, _, _, _, _ = classification_metrics(
                        output[idx_train], labels[idx_train])
                    # _, _, _, _ = fair_metric(
                    #     labels, output, idx_train, sens, 'train')
                    loss_train.backward()
                    optimizer.step()

                    if not args.fastmode:
                        # Evaluate validation set performance separately,
                        # deactivates dropout during validation run.
                        model.eval()
                        output = model(features)

                acc_val, roc_val, _, _, _, _ = classification_metrics(
                    output[idx_val], labels[idx_val])
                # _,_,_,_ = fair_metric(
                #     labels, output, idx_val, sens, 'val')
                acc_test, roc_test, p, r, maf1_test, mif1_test = classification_metrics(
                    output[idx_test], labels[idx_test])
                parity, equality, eq_odds, middle_results = fair_metric(
                    labels, output, idx_test, sens, 'test')

                print("Epoch [{}] Test set results:".format(epoch),
                      "acc_test= {:.4f}".format(acc_test.item()),
                      "acc_val: {:.4f}".format(acc_val.item()))
                if acc_val > args.acc:  # and roc_val > args.roc:
                    if acc_val > vali_max[0]:
                        vali_max = [
                            acc_val, [
                                acc_test.item(), roc_test, p, r, maf1_test, mif1_test], [
                                parity, equality, eq_odds], epoch + 1, middle_results]

                    print("=================================")

                    print('Epoch: {:04d}'.format(epoch + 1),
                          'acc_train: {:.4f}'.format(acc_train.item()),
                          'acc_val: {:.4f}'.format(acc_val.item()),
                          "roc_val: {:.4f}".format(roc_val))
                    print("Test:",
                          "accuracy: {:.4f}".format(acc_test.item()),
                          "roc: {:.4f}".format(roc_test),
                          "parity: {:.4f}".format(parity),
                          "equality: {:.4f}".format(equality))
                    print("Best:",
                          "accuracy: {:.4f}".format(vali_max[1][0]),
                          "parity: {:.4f}".format(vali_max[2][0]),
                          "epoch: {0}".format(vali_max[3]))
            FINAL_RESULT.append(list(vali_max))
            print("Optimization Finished!")
            print("Total time elapsed: {:.4f}s".format(time.time() - t_total))

            print('============performace on test set=============')
            # if len(best_result) > 0:
            print("Test:",
                  "accuracy: {:.4f}".format(vali_max[1][0]),
                  "auc: {:.4f}".format(vali_max[1][1]),
                  "precision: {:.4f}".format(vali_max[1][2]),
                  "recall: {:.4f}".format(vali_max[1][3]),
                  "maf1: {:.4f}".format(vali_max[1][4]),
                  "mif1: {:.4f}".format(vali_max[1][5]),
                  "parity: {:.4f}".format(vali_max[2][0]),
                  "equality: {:.4f}".format(vali_max[2][1]),
                  "eq odds: {:.4f}".format(vali_max[2][2]),
                  "epoch: {0}".format(vali_max[3]))
            # else:
            #     print("Please set smaller acc/roc thresholds")
        print("\n")
        sum_acc = []
        sum_roc = []
        sum_p = []
        sum_r = []
        sum_maf1 = []
        sum_mif1 = []

        sum_sp = []
        sum_eq = []
        sum_eo = []
        for i in range(len(FINAL_RESULT)):
            print(
                "{0}:\tvali: {1:.4f}\t | test:  ACC: {2:.4f} AUC: {3:.4f} Precision:: {4:.4f} Recall: {5:.4f} MaF1: {6:.4f} MiF1: {7:.4f}, Parity:: {8:.4f} Equality:: {9:.4f} Eq_odds:: {10:.4f}".format(
                    i,
                    FINAL_RESULT[i][0],
                    FINAL_RESULT[i][1][0],
                    FINAL_RESULT[i][1][1],
                    FINAL_RESULT[i][1][2],
                    FINAL_RESULT[i][1][3],
                    FINAL_RESULT[i][1][4],
                    FINAL_RESULT[i][1][5],
                    FINAL_RESULT[i][2][0],
                    FINAL_RESULT[i][2][1],
                    FINAL_RESULT[i][2][2]))
            print("epoch=", FINAL_RESULT[i][3])
            sum_acc.append(FINAL_RESULT[i][1][0])
            sum_roc.append(FINAL_RESULT[i][1][1])
            sum_p.append(FINAL_RESULT[i][1][2])
            sum_r.append(FINAL_RESULT[i][1][3])
            sum_maf1.append(FINAL_RESULT[i][1][4])
            sum_mif1.append(FINAL_RESULT[i][1][5])
            sum_sp.append(FINAL_RESULT[i][2][0])
            sum_eq.append(FINAL_RESULT[i][2][1])
            sum_eo.append(FINAL_RESULT[i][2][2])
        print("mean test acc:", np.mean(sum_acc))
        print("std test acc:", np.std(sum_acc))
        print("mean test roc:", np.mean(sum_roc))
        print("std test roc:", np.std(sum_roc))
        print("mean test precision:", np.mean(sum_p))
        print("std test precision:", np.std(sum_p))
        print("mean test recall:", np.mean(sum_r))
        print("std test recall:", np.std(sum_r))
        print("mean test maf1:", np.mean(sum_maf1))
        print("std test maf1:", np.std(sum_maf1))
        print("mean test mif1:", np.mean(sum_mif1))
        print("std test mif1:", np.std(sum_mif1))

        print("mean test statistical parity:", np.mean(sum_sp))
        print("std test statistical parity:", np.std(sum_sp))
        print("mean test equal opportunity:", np.mean(sum_eq))
        print("std test equal opportunity:", np.std(sum_eq))
        print("mean test equal odds:", np.mean(sum_eo))
        print("std test equal odds:", np.std(sum_eo))

        FINAL_RESULT_DICT_LIST = []

        for i in range(N):
            FINAL_RESULT_DICT = {}
            FINAL_RESULT_DICT['acc'] = FINAL_RESULT[i][1][0]
            FINAL_RESULT_DICT['auc'] = FINAL_RESULT[i][1][1]
            FINAL_RESULT_DICT['precision'] = FINAL_RESULT[i][1][2]
            FINAL_RESULT_DICT['recall'] = FINAL_RESULT[i][1][3]
            FINAL_RESULT_DICT['maf1'] = FINAL_RESULT[i][1][4]
            FINAL_RESULT_DICT['mif1'] = FINAL_RESULT[i][1][5]

            FINAL_RESULT_DICT['yp1.a1'] = FINAL_RESULT[i][4]['yp1.a1']
            FINAL_RESULT_DICT['yp1.a0'] = FINAL_RESULT[i][4]['yp1.a0']
            FINAL_RESULT_DICT['yp1.y1a1'] = FINAL_RESULT[i][4]['yp1.y1a1']
            FINAL_RESULT_DICT['yp1.y1a0'] = FINAL_RESULT[i][4]['yp1.y1a0']
            FINAL_RESULT_DICT['yp1.y0a1'] = FINAL_RESULT[i][4]['yp1.y0a1']
            FINAL_RESULT_DICT['yp1.y0a0'] = FINAL_RESULT[i][4]['yp1.y0a0']

            FINAL_RESULT_DICT['parity'] = FINAL_RESULT[i][2][0]
            FINAL_RESULT_DICT['equality'] = FINAL_RESULT[i][2][1]
            FINAL_RESULT_DICT['eq_odds'] = FINAL_RESULT[i][2][2]

            FINAL_RESULT_DICT_LIST.append(FINAL_RESULT_DICT)
        #
        fieldnames = [
            'acc',
            'auc',
            'precision',
            'recall',
            'maf1',
            'mif1',
            'yp1.a1',
            'yp1.a0',
            'yp1.y1a1',
            'yp1.y1a0',
            'yp1.y0a1',
            'yp1.y0a0',
            'parity',
            'equality',
            'eq_odds']
        fname = '../results/result-' + str(args.dataset) + (
            ('-' + args.sensitive) if 'pokec' in args.dataset else '') + '-' + str(model_name) + \
                '-' + str(args.attack_type) + (('-' + args.direction + '-' + args.strategy + '-deg' + str(
            args.deg) + '-' + str(args.deg_direction)) if args.attack_type == 'fair_attack' else '') + \
                (f'-{ptb_rate:.2f}' if args.attack_type != 'none' else '') + '-' + str(args.train_percent_atk) + '.csv'
        with open(fname, 'w', encoding='UTF8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(FINAL_RESULT_DICT_LIST)
        f.close()
