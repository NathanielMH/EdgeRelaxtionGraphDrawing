import sys
import os

module_path = os.path.abspath(os.path.join('..'))
if module_path not in sys.path:
    sys.path.append(module_path)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
from tqdm import tqdm
import networkx as nx
import xgboost as xgb
import pickle

from xgb_model import preprocess_data, make_predictions
from src.graph_utils import compareGraphs, quality_measures
from general.data_generation import graph_to_df, draw_fa2, draw_kk

# Replace what is up there with preprocess data function.

# Have compare Graph output write the result in a file instead of showing it.

algo_dict = {'fa2': draw_fa2, 'kk': draw_kk}

#####
# Auxiliary functions 
#####
def bfs_on_edges(g: nx.Graph, edge: list or tuple, depth_limit) -> list:
    bfs_edges = {edge}
    sp = dict(nx.all_pairs_shortest_path_length(g))
    for e in nx.edge_bfs(g, edge[0]):
        if sp[e[0]][edge[0]] == depth_limit+1 or sp[e[1]][edge[0]] == depth_limit+1:
            break
        bfs_edges.add(e)
    
    for e in nx.edge_bfs(g, edge[1]):
        if sp[e[0]][edge[1]] == depth_limit+1 or sp[e[1]][edge[1]] == depth_limit+1:
            break
        bfs_edges.add(e)

    return list(bfs_edges)



#####
# Drawing functions 
#####

def relax_one(graph: nx.Graph, draw_f, model: XGBClassifier, data: pd.DataFrame = None, thresh: float = 0.5) -> dict:
    """Relax only best edge
    
    Args:
        graph (nx.Graph): graph to relax
        draw_f (function): function to draw the graph
        model (XGBClassifier): model to use for predictions on which edge to relax
        data (pd.DataFrame): data to use for predictions. If None, it will be computed from the graph

    Returns:
        pos (dict): final positions of the nodes
    """
    if data is None:
        data = graph_to_df(graph,0,draw_f,bench='Test',include_labels=False)
        X = preprocess_data(data, return_labels=False, drop_labels=False)
    else:
        X = preprocess_data(data, return_labels=False, drop_labels=True)
    proba = make_predictions(model, X)

    max_proba_idx = np.argmax(proba)
    max_proba_edge = list(graph.edges)[max_proba_idx]

    g2 = graph.copy()
    g2.remove_edges_from([max_proba_edge])
    
    pos = draw_f(g2, pos=draw_f(graph))
    return pos

def just_relax(graph: nx.Graph, draw_f, model: XGBClassifier, data: pd.DataFrame = None, thresh: float = 0.5) -> dict:
    """Relax all edges with prob > thresh
    
    Args:
        graph (nx.Graph): graph to relax
        draw_f (function): function to draw the graph
        model (XGBClassifier): model to use for predictions on which edge to relax
        data (pd.DataFrame): data to use for predictions. If None, it will be computed from the graph
        thresh (float): threshold to select edges. Default is 0.5.

    Returns:
        pos (dict): final positions of the nodes
    """
    if data is None:
        data = graph_to_df(graph,0,draw_f,bench='Test', include_labels=False)
        X = preprocess_data(data,return_labels=False,drop_labels=False)
    else:
        X = preprocess_data(data,return_labels=False,drop_labels=True)
    proba = np.array(make_predictions(model, X))

    selected_idxs = np.argwhere(proba>0.5).flatten()
    selected_edges = [list(graph.edges)[idx] for idx in selected_idxs]

    g2 = graph.copy()
    g2.remove_edges_from(selected_edges)
    
    pos = draw_f(g2, pos=draw_f(graph))

    return pos


def relax_block(graph: nx.Graph, draw_f, model: XGBClassifier, data: pd.DataFrame = None, depth_limit: int = 3, num_it = 5) -> dict:
    """Relax 1 edge -> block near edges -> relax 1 edge -> block near edges -> ... 
    
    Args:
        graph (nx.Graph): graph to relax
        draw_f (function): function to draw the graph
        model (XGBClassifier): model to use for predictions on which edge to relax
        data (pd.DataFrame): data to use for predictions. If None, it will be computed from the graph
        depth_limit (int): number of bfs steps to block. Default is 3.

    Returns:
        pos (dict): final positions of the nodes
    """
    if data is None:
        data = graph_to_df(graph,0,draw_f,bench='Test', include_labels=False)
        X = preprocess_data(data,return_labels=False,drop_labels=False)
    else:
        X = preprocess_data(data,return_labels=False,drop_labels=True)
    proba = np.array(make_predictions(model, X)).flatten()

    diff_crossings = -1
    relaxed_edges = []
    diff_crossings_hist = []

    g2 = graph.copy()

    edge2idx = {e:idx for idx, e in enumerate(graph.edges)}
    for idx, e in enumerate(graph.edges):
        edge2idx[e[::-1]] = idx

    # print(np.max(list(edge2idx.values())))
    # print(len(proba))

    for it in range(num_it):
        max_proba_idx = np.argmax(proba)
        max_proba_edge = list(graph.edges)[max_proba_idx]
        relaxed_edges.append(max_proba_edge)
        
        edges2block = bfs_on_edges(graph, max_proba_edge, depth_limit)
        idxedges2block = [edge2idx[e] for e in edges2block]

        for e in [max_proba_idx, *idxedges2block]:
            proba[e] = -1

        g2.remove_edges_from([max_proba_edge])

        diff_crossings = compareGraphs(graph, graph, draw_f(graph), draw_f(g2), show=False)[0]
        diff_crossings_hist.append(diff_crossings)
    
    min_crossings_idx = np.argmin(diff_crossings_hist)

    g2 = graph.copy()

    g2.remove_edges_from(relaxed_edges[:min_crossings_idx])

    pos = draw_f(g2, pos=draw_f(graph))

    return pos

def relax_and_recompute(graph: nx.Graph, draw_f, model: XGBClassifier, data: pd.DataFrame = None, k: int = 3) -> dict:
    """Relax 1 edge -> recompute -> relax 1 edge -> recompute -> ... k times
    
    Args:
        graph (nx.Graph): graph to relax
        draw_f (function): function to draw the graph
        model (XGBClassifier): model to use for predictions on which edge to relax
        data (pd.DataFrame): data to use for predictions. If None, it will be computed from the graph
        k (int): number of times we execute the procedure. Default is 3.

    Returns:
        pos (dict): final positions of the nodes
    """
    if data is None:
        data = graph_to_df(graph,0,draw_f,bench='Test', include_labels=False)
        X = preprocess_data(data,return_labels=False,drop_labels=False)
    else:
        X = preprocess_data(data,return_labels=False,drop_labels=True)
    proba = make_predictions(model,X)
    removed_edges = []
    pos0 = draw_f(graph)
    pos1 = pos0
    for i in range(k):
        max_proba_idx = np.argmax(proba)
        max_proba_edge = list(graph.edges)[max_proba_idx]
        removed_edges.append(max_proba_edge)

        g2 = graph.copy()
        g2.remove_edges_from([max_proba_edge])
        pos1 = draw_f(g2,pos=pos1)

        data = graph_to_df(g2,0,draw_f,bench='Test',include_labels=False)
        X = preprocess_data(data,return_labels=False,drop_labels=False)
        proba = make_predictions(model,X)
    return pos1
#####
# Evaluation functions 
#####

def eval(model: XGBClassifier, df: pd.DataFrame, graphid2src: dict, method, results_file: str, draw_f,**kwargs) -> None:
    """Evaluate the given method with the given model on the given graphs
    
    Args:
        model (XGBClassifier): The model to use
        df (pd.Dataframe): The dataframe containing the graph data
        graphid2src (dict): A dictionary mapping graph ids to the graph objects
        method (function): The function used to generate the new layout
        results_file (str): The file to save the results to
        draw_f (function): The function used to draw the graphs
        method_name (str): The name of the method
        **kwargs: Additional arguments to pass to the method depending on the method
    
    Returns:
        None
    """

    method_name = method.__name__

    # Initialize quality measures
    average_percentage_edge_cross_reduction = 0.
    average_edge_cross_angle_reduction = 0.
    average_aspect_ratio_reduction = 0.
    average_edge_cross_reduction = 0.

    # Iterate over all graphs
    id_list = df['graph_id'].unique()
    for graphid, g in tqdm(graphid2src.items()):
        if graphid not in id_list:
            continue
        #print(f"Processing graph {graphid}")
        data = df[df['graph_id'] == graphid]
        pos0 = draw_f(g)
        if method_name == 'relax_one':
            pos1 = method(g, draw_f, model, data)
        elif method_name == 'just_relax':
            pos1 = method(g, draw_f, model, data)
        elif method_name == 'relax_block':
            pos1 = method(g, draw_f, model, data, kwargs['depth_limit'])
        else:
            pos1 = method(g, draw_f, model, data, kwargs['k'])
        
        # Compute quality measures for both layouts
        num_crossings0, aspect_ratio0, mean_crossing_angle0, _, _, _, _ = quality_measures(g, pos=pos0)
        num_crossings1, aspect_ratio1, mean_crossing_angle1, _, _, _, _ = quality_measures(g, pos=pos1)

        # Compute the comparing metrics
        if num_crossings0:
            average_percentage_edge_cross_reduction += (num_crossings0 - num_crossings1) / num_crossings0
        average_edge_cross_angle_reduction += mean_crossing_angle0 - mean_crossing_angle1
        average_aspect_ratio_reduction += aspect_ratio0 - aspect_ratio1
        average_edge_cross_reduction += num_crossings0 - num_crossings1

    # Normalize comparing metrics
    average_percentage_edge_cross_reduction /= len(graphid2src)
    average_percentage_edge_cross_reduction *= 100
    average_edge_cross_angle_reduction /= len(graphid2src)
    average_aspect_ratio_reduction /= len(graphid2src)
    average_edge_cross_reduction /= len(graphid2src)

    # Write results to file
    with open(results_file, 'a') as f:
        f.write(f"Method used: {method_name} \n \
            Average of percentage of edge crossing reduction: {average_percentage_edge_cross_reduction} \n \
            Average of edge cross angle reduction: {average_edge_cross_angle_reduction}\n \
            Average of aspect ratio reduction: {average_aspect_ratio_reduction} \n \
            Average of edge cross reduction: {average_edge_cross_reduction} \n")


def main(alg_name: str = 'kk'):
    model = xgb.XGBClassifier()
    model.load_model('../data/xgb_'+alg_name+'.bin')
    df = pd.read_csv('../data/graph_train_experiment_'+alg_name+'.csv')
    with open('../data/idToGraph.pickle', 'rb') as f:
        graphid2src = pickle.load(f)
    draw_f = algo_dict[alg_name]
    eval(model, df, graphid2src, relax_block, 'first_analysis.txt', draw_f, depth_limit=2)

if __name__ == '__main__':
    main('kk')
    main('fa2')