from lcopt.bw2_export import Bw2Exporter

import brightway2 as bw2
import bw2analyzer

from bw2analyzer.tagged import recurse_tagged_database, aggregate_tagged_graph

import matplotlib.pyplot as plt


import networkx as nx

from copy import deepcopy
from itertools import groupby

import json

plt.style.use('ggplot')
plt.rcParams['figure.figsize'] = (5, 5)

class Bw2Analysis():
    def __init__(self, modelInstance):
        self.modelInstance = modelInstance
        self.exporter = Bw2Exporter(modelInstance)
        
        self.bw2_database_name, self.bw2_database = self.exporter.export_to_bw2()
        
        self.bw2_project_name = self.modelInstance.name
        
    def setup_bw2(self):
        if self.bw2_project_name in bw2.projects:
            bw2.projects.set_current(self.bw2_project_name)
            print ('Switched to existing bw2 project - {}'.format(self.bw2_project_name))
            return True
            
        elif 'setup_TO_COPY' in bw2.projects:
            bw2.projects.set_current('setup_TO_COPY')
            bw2.projects.copy_project(self.bw2_project_name, switch = True)
            print ('Created new bw2 project - {}'.format(self.bw2_project_name))
            return True
        
        else:
            print ("bw2 project setup failed, please create the 'setup_TO_COPY' project in advance with the biosphere and necessary external databases (e.g. 'Ecoinvent_3_3_cutoff') ")
            return False
        
    def update_exchange_amounts(self, database, parameter_set):
        for i in database:

            for e in i.exchanges():

                if 'parameter_hook' in e.keys():
                    #print (i)
                    #print("\t {}".format(e))
                    #print("\t\t {}".format(e['parameter_hook']))
                    #print("\t\t {}".format(e.amount))
                    e['amount'] = parameter_set[e['parameter_hook']]
                    #print("\t\t {}".format(e.amount))
                    e.save()
    
    def multi_recurse(self, d):
    
        max_levels = 100

        this_d = d

        for i in range(max_levels):
            prev_d = this_d
            this_d = self.recurse(prev_d)
            if this_d == prev_d:
                #print('breaking after {} levels'.format(i+1))
                break

        return this_d



    def recurse(self, d):

        to_return = {}
        cum_impact = 0

        for k, v in d.items():
            if k == 'technosphere':
                #print('technosphere')
                for e in v:
                    #print (e['activity'])
                    cum_impact += e['impact']
                    if 'cum_impact' in e.keys():
                        cum_impact += e['cum_impact']

                    if k in to_return.keys():
                        to_return[k].append(self.recurse(e))
                    else:
                        to_return[k]=[self.recurse(e)]
                        
            elif k == 'biosphere':
                to_return[k] = v
                if len(v) != 0:
                    for b in v:
                        cum_impact += b['impact']
                        
            elif k == 'activity':
                #print (k,v)
                to_return[k] = str(v)
            #elif k == 'impact':
             #   print('impact of {} = {}'.format(d['activity'], v))

            else:
                to_return[k] = v
        #print('cum_impact of {} = {}'.format(d['activity'], cum_impact))
        to_return['cum_impact'] = cum_impact
            
        return to_return
    
    def run_analyses(self, demand_item, demand_item_code,  amount = 1, methods = [('IPCC 2013', 'climate change', 'GWP 100a')], top_processes = 10, gt_cutoff = 0.01, pie_cutoff =0.05):
        
        ready = self.setup_bw2()
        name = self.bw2_database_name
        
        if ready:
            if name in bw2.databases:
                del bw2.databases[name]
                print ('Rewriting database ({}) ...'.format(name))
            else:
                print ('Writing database ({})...'.format(name))
            new_db = bw2.Database(name)
            
            new_db.write(self.bw2_database)
            new_db.process()
            
            print ('trying to get {}'.format(demand_item_code))
            product_demand = new_db.get(demand_item_code)
            
            if product_demand != False:
                
                fu = {product_demand:amount}
                
               
                result_dict = {
                    'settings':{
                        'pie_cutoff': pie_cutoff,
                        'methods': [str(method) for method in methods],
                        'method_names' : [method[1] for method in methods],
                        'method_units' : [bw2.methods[method]['unit'] for method in methods],
                        'item': demand_item,
                        'item_code': demand_item_code,
                        'amount': amount,
                        }
                    }
                result_sets = []
                parameter_sets = self.modelInstance.evaluated_parameter_sets

                #for each parameter set in the model run the analysis

                for n, (parameter_set_name, parameter_set) in enumerate(parameter_sets.items()):
                    
                    # update the parameter_set values
                    print ('\nAnalysis {}\n'.format(n+1))
                    
                    self.update_exchange_amounts(new_db, parameter_set)
                    
                    
                    initial_method = methods[0]
                    # run the LCA
                    lca = bw2.LCA(fu, initial_method)
                    lca.lci(factorize = True)
                    lca.lcia()
                    
                    ps_results = []

                    for method in methods:
                        lca.switch_method(method)
                        lca.redo_lcia(fu)
                        unit = bw2.methods[method]['unit']
                        
                        score = lca.score
                        print('Analysis for {} {} of {}, using {}'.format(amount, product_demand['unit'], product_demand['name'], method))
                        print ('{:.3g} {}'.format(score, unit))
                        
                        method_dict = {o[0]: o[1] for o in bw2.Method(method).load()}
                        default_tag = "other"

                        label = "lcopt_type"
                        type_graph = [recurse_tagged_database(key, amount, method_dict, lca, label, default_tag)
                                 for key, amount in fu.items()]
                        type_result = aggregate_tagged_graph(type_graph)
                        
                        #for k,v in type_result.items():
                        #    print('{}\t\t{}'.format(k,v))
                        
                        label = "name"
                        foreground_graph = [recurse_tagged_database(key, amount, method_dict, lca, label, default_tag)
                                 for key, amount in fu.items()]
                        foreground_result = aggregate_tagged_graph(foreground_graph)
                        
                        #for k,v in foreground_result.items():
                        #    print('{}\t\t{}'.format(k,v))
                            
                        recursed_graph = self.multi_recurse(type_graph[0])
                        
                        result_set = {
                            'method':str(method),
                            'unit' : unit,
                            'score':score,
                            'foreground_results':foreground_result,
                            'graph': recursed_graph,
                        }
                        
                        ps_results.append(result_set)
                        
                    result_sets.append(ps_results)

                result_dict['results'] = result_sets
                    
                return result_dict
                        
                        
                