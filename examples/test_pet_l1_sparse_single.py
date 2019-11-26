import torch
import argparse
import os
from dist_stat.pet_utils import *
from dist_stat.pet_l1_single import PET_L1
import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy import sparse

def coo_to_sparsetensor(spm, TType=torch.DoubleTensor):
    typename = torch.typename(TType).split('.')[-1]
    TType_cuda = TType.is_cuda
    densemodule = torch.cuda if TType_cuda else torch
    spmodule = torch.cuda.sparse if TType_cuda else torch.sparse
    TType_sp = getattr(spmodule, typename)
    i = densemodule.LongTensor(np.vstack([spm.row, spm.col]))
    v = TType(spm.data)
    return TType_sp(i, v, spm.shape)

import torch.distributed as dist
dist.init_process_group('mpi')
rank = dist.get_rank()
size = dist.get_world_size()

if 'CUDA_VISIBLE_DEVICES' in os.environ.keys():
    os.environ['CUDA_VISIBLE_DEVICES'] = '0,1,2,3'
    num_gpu=4
else:
    num_gpu=8

if __name__=='__main__':
    parser = argparse.ArgumentParser(description="nmf testing")
    parser.add_argument('--gpu', dest='with_gpu', action='store_const', const=True, default=False, 
                        help='whether to use gpu')
    parser.add_argument('--double', dest='double', action='store_const', const=True, default=False, 
                        help='use this flag for double precision. otherwise single precision is used.')
    parser.add_argument('--nosubnormal', dest='nosubnormal', action='store_const', const=True, default=False, 
                        help='use this flag to avoid subnormal number.')
    parser.add_argument('--tol', dest='tol', action='store', default=0, 
                        help='error tolerance')
    parser.add_argument('--rho', dest='rho', action='store', default=0, 
                        help='penalty parameter')
    parser.add_argument('--offset', dest='offset', action='store', default=0, 
                        help='gpu id offset')
    parser.add_argument('--data', dest='data', action='store', default='../data/pet_100_180.npz', 
                        help='data file (.npz)')
    parser.add_argument('--sparse', dest='sparse', action='store_const', default=False, const=True, 
                        help='use sparse data matrix')
    parser.add_argument('--iter', dest='iter', action='store', default=1000, 
                        help='max iter')
    args = parser.parse_args()
    if args.with_gpu:
        divisor = size//num_gpu
        if divisor==0:
            torch.cuda.set_device(rank+int(args.offset))
        else:
            torch.cuda.set_device(rank//divisor)
        if args.double:
            TType=torch.cuda.DoubleTensor
        else:
            TType=torch.cuda.FloatTensor
    else:
        if args.double:
            TType=torch.DoubleTensor
        else:
            TType=torch.FloatTensor
    if args.nosubnormal:
        torch.set_flush_denormal(True)
        #floatlib.set_ftz()
        #floatlib.set_daz()

    rank = 0
    size = 1



    datafile = np.load(args.data)


    n_x = datafile['n_x']
    n_t = datafile['n_t']
   
    # load e
    TType_name = torch.typename(TType).split('.')[-1]
    TType_sp   = getattr(torch.sparse, TType_name)
    if args.with_gpu:
        TType_sp   = getattr(torch.cuda.sparse, TType_name)
    #print(TType_sp)

    #e = torch.Tensor(datafile['e']).type(TType)
    e_indices = datafile["e_indices"]
    e_values = datafile["e_values"]

    p = n_x**2
    d = n_t * (n_t - 1) // 2
    #p_chunk_size = p//size

    
    e_coo = coo_matrix((e_values, (e_indices[0,:], e_indices[1,:])), shape=(d, p))
    e_csc = e_coo.tocsc()
    #e_csc_chunk = e_csc[:, (rank*p_chunk_size):((rank+1)*p_chunk_size)]
    e_coo = e_csc.tocoo()
    e_values = TType(e_coo.data)
    e_rows = torch.LongTensor(e_coo.row)
    e_cols = torch.LongTensor(e_coo.col)
    if e_values.is_cuda:
        e_rows = e_rows.cuda()
        e_cols = e_cols.cuda()
    e_indices = torch.stack([e_rows, e_cols], dim=1).t()
    e_shape = e_coo.shape
    e_size = torch.Size([int(e_shape[0]), int(e_shape[1])])
    e_mat = TType_sp(e_indices, e_values, e_size).t()

    if args.sparse:
        e_mat = e_mat.t()
    else:
        e_mat = e_mat.to_dense().t()

    # load D
    D_coo = sparse.coo_matrix((datafile['D_values'], 
                                (datafile['D_indices'][0,:], datafile['D_indices'][1,:])), 
                                shape=datafile['D_shape'])
    D_csr = D_coo.tocsr()
    D_coo = D_csr.tocoo()
    D_values = TType(D_coo.data)
    D_rows   = torch.LongTensor(D_coo.row)
    D_cols   = torch.LongTensor(D_coo.col)
    if D_values.is_cuda:
        D_rows = D_rows.cuda()
        D_cols = D_cols.cuda()
    D_indices = torch.stack([D_rows, D_cols], dim=1).t()
    D_shape = D_coo.shape
    D_size  = torch.Size([int(D_shape[0]), int(D_shape[1])])
    D_mat = TType_sp(D_indices, D_values, D_size)
    

    counts = TType(datafile['counts']) # put everywhere

    pet = PET_L1(counts, e_mat, D_mat, sig=1/3, tau=1/3, rho=float(args.rho), TType=TType)
    pet.run(check_obj=True, tol=float(args.tol), check_interval=100, maxiter=int(args.iter))