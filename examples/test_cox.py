import torch
import torch.distributed as dist
dist.init_process_group('mpi')
rank = dist.get_rank()
size = dist.get_world_size()

from dist_stat import distmat
from dist_stat import distmm

from dist_stat import cox_cumsum as cox
import argparse
import os
if 'CUDA_VISIBLE_DEVICES' in os.environ.keys():
    os.environ['CUDA_VISIBLE_DEVICES'] = '0,1,2,3'
    num_gpu=4
else:
    num_gpu=8
#import pyximport
#pyximport.install()
#import floatlib


if __name__=='__main__':
    parser = argparse.ArgumentParser(description="cox testing")
    parser.add_argument('--gpu', dest='with_gpu', action='store_const', const=True, default=False, 
                        help='whether to use gpu')
    parser.add_argument('--double', dest='double', action='store_const', const=True, default=False, 
                        help='use this flag for double precision. otherwise single precision is used.')
    parser.add_argument('--tol', dest='tol', action='store', default=0.0, 
                        help='relative tolerence')
    parser.add_argument('--lambda', dest='lambd', action='store', default=0.0001, 
                        help='penalty parameter')
    parser.add_argument('--iter', dest='iter', action='store', default=10000, 
                        help='max iter')
    parser.add_argument('--nosubnormal', dest='nosubnormal', action='store_const', const=True, default=False, 
                        help='use this flag to avoid subnormal number.')
    parser.add_argument('--step', dest='step', action='store',  default=100, 
                        help='evaluation intervals')
    parser.add_argument('--rows', dest='rows', action='store', default=10000)
    parser.add_argument('--cols', dest='cols', action='store', default=10000)
    parser.add_argument('--datnormest', dest='datnormest', action='store', default=None)
    parser.add_argument('--quicknorm', dest='quicknorm', action='store_const', const=True, default=False)
    args = parser.parse_args()
    if args.with_gpu:
        divisor = size //num_gpu
        if divisor ==0:
            torch.cuda.set_device(rank)
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
    seed=95376
    torch.manual_seed(seed)
    n = int(args.cols); p = int(args.rows)
    X = distmat.distgen_normal(p, n, TType=TType, set_from_master=True)
    torch.manual_seed(seed+100)
    delta = torch.multinomial(torch.tensor([1., 1.]), n, replacement=True).float().view(-1, 1).type(TType)
    if args.datnormest:
        cox_driver = cox.COX(X.t(), delta, float(args.lambd), seed=seed+200, TType=TType, sigma=1.0/(2*float(args.datnormest)**2))
    elif args.quicknorm:
        cox_driver = cox.COX(X.t(), delta, float(args.lambd), seed=seed+200, TType=TType, sigma='quicknorm')
    else:
        cox_driver = cox.COX(X.t(), delta, float(args.lambd), seed=seed+200, TType=TType, sigma='power')  
    cox_driver.run(int(args.iter), tol=float(args.tol),check_interval=int(args.step), check_obj=True)
    print((cox_driver.beta == 0).chunk.sum())
